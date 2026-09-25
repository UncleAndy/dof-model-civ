#!/usr/bin/env python3
"""
Real CivRealm tournament runner.

Plays actual games against a running Freeciv-web server so that agent actions
genuinely affect the game state, and measures every agent through the same
recorder (:mod:`metrics.tracker`) so the comparison is apples-to-apples.

Usage:
    bash do.sh real-tournament --episodes 15 --turns 30 --only random,dof_defensive
    bash do.sh real-tournament --episodes 15 --turns 30 --output tournament_results.json

Operational notes
-----------------
* CivRealm agent "ports" are server-side game slots. Singleplayer/pbem occupy
  6000-6009, the idle multiplayer pool handed out by ``Ports.get()`` is
  6300-6331. A slot is single-use *until its game ends*: Publite2 restarts it
  and the slot returns to the pool, so long runs cycle through the same slots
  without restarting the container.
* ``env.reset`` and ``Ports.get`` block forever with no free slot, so every
  match is guarded by a wall-clock alarm.
* Gymnasium's passive env checker warns on CivRealm's non-standard observation
  space; those warnings are silenced on purpose.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"


# CivRealm's config module runs its own argparse over sys.argv at import time,
# so our CLI must be resolved before civrealm is imported and the leftover
# arguments handed back untouched.
def _parse_cli(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_real_tournament.py",
        description="Real CivRealm tournament (agents play actual games).",
    )
    parser.add_argument("--episodes", type=int, default=15,
                        help="matches per agent")
    parser.add_argument("--turns", type=int, default=30,
                        help="max decision steps per match")
    parser.add_argument("--port", type=int, default=6001,
                        help="base slot; only used when --no-auto-port is set")
    parser.add_argument("--timeout", type=int, default=240,
                        help="per-match wall-clock budget in seconds")
    parser.add_argument("--auto-port", dest="auto_port", action="store_true",
                        default=True,
                        help="pick a free slot via civrealm Ports.get() (default)")
    parser.add_argument("--no-auto-port", dest="auto_port", action="store_false",
                        help="use --port + episode index instead")
    parser.add_argument("--port-wait", type=int, default=120,
                        help="seconds to wait for a free slot before falling back")
    parser.add_argument("--retries", type=int, default=2,
                        help="extra attempts per match when the server stalls")
    parser.add_argument("--settle", type=float, default=2.0,
                        help="seconds to wait between matches")
    parser.add_argument("--seed-base", type=int, default=None,
                        help="if set, episode i calls env.reset(seed=seed_base+i). "
                             "NOTE: observed ineffective on the standard stand -- "
                             "Publite2 creates the game (and its map) before the "
                             "client connects, so episodes repeat the SAME scenario. "
                             "Confidence intervals are therefore within-scenario, "
                             "not across environments.")
    parser.add_argument("--only", type=str, default="",
                        help="comma-separated agent subset, e.g. random,dof_defensive")
    parser.add_argument("--save-series", dest="save_series", action="store_true",
                        default=False,
                        help="also persist per-step DoF/entity/action series "
                             "(larger JSON, enables trajectory analysis)")
    parser.add_argument("--output", type=str, help="write per-episode metrics to JSON")
    args, rest = parser.parse_known_args(argv)
    sys.argv = [sys.argv[0]] + rest
    return args


ARGS = _parse_cli(sys.argv[1:])

import gymnasium
from civrealm.configs import fc_args
from civrealm.agents import RandomAgent, BaseAgent

from env.entity_extractor import GameStateExtractor, compute_total_dof_index
from brain.generator.heuristics import ALL_STRATEGIES, DEFENSIVE, HeuristicGenerator
from metrics.tracker import MatchMetrics, agent_turns

# DOF-Core decision engine. The tournament must exercise the actual object of
# study: the Rust core owns the Axiom-3 veto and the Axiom-4 context-switch
# penalty for irreversible actions, and it declines to act when every option has
# a negative net delta (Decision Calculus §4).
try:
    from dof_core import CoreAction, CoreEntity, DOFCalculusCore

    HAVE_DOF_CORE = True
except Exception:  # noqa: BLE001 - Python fallback keeps the runner usable
    HAVE_DOF_CORE = False

# Slots: singleplayer/pbem 6000-6009, idle multiplayer pool 6300-6331.
MIN_PORT = 6000
MAX_PORT = 6331


class MatchTimeout(Exception):
    """Raised when a single match exceeds its wall-clock budget."""


def _on_alarm(signum, frame):  # pragma: no cover - signal path
    raise MatchTimeout("match exceeded wall-clock budget")


# Backwards-compatible alias (older scripts imported MatchResult).
MatchResult = MatchMetrics


class NoOpAgent(BaseAgent):
    """Baseline that never issues an action."""

    def act(self, observations, info):
        return None


def allocate_port(wait: int = 120):
    """Ask civrealm for a free slot, or None if none appears in ``wait`` seconds.

    ``Ports.get()`` loops forever when no slot is free, so it is alarm-guarded.
    Slots are recycled by Publite2 after a game ends, so waiting is normal in a
    long run.
    """
    try:
        from civrealm.freeciv.utils.port_utils import Ports
    except Exception:  # noqa: BLE001 - status endpoint unreachable
        return None

    def _alarm(signum, frame):
        raise MatchTimeout("no free slot")

    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(max(1, wait))
    try:
        return Ports.get()
    except (MatchTimeout, Exception):  # noqa: BLE001
        return None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _to_action(candidate: dict):
    """Candidate -> the (ctrl_type, actor_id, action_name) tuple env.step wants.

    Uses the structured fields: actor ids and action names may contain
    underscores and spaces, and actor ids may be ints or strings.
    """
    ctrl_type = candidate.get('ctrl_type')
    actor_id = candidate.get('actor_id')
    action_name = candidate.get('action_name')
    if ctrl_type is None or actor_id is None or action_name is None:
        return None
    return (ctrl_type, actor_id, action_name)


def _core_entities(state) -> list:
    """SystemStateMatrix -> Rust core entity list."""
    return [
        CoreEntity(
            entity_id=e.entity_id,
            current_dof=e.current_dof,
            is_collapse_source=e.is_collapse_source,
            is_reversible=e.time_to_collapse_mks > 1e14,
        )
        for e in state.entities.values()
    ]


def _core_actions(candidates: list[dict]) -> list:
    """DOF candidates -> Rust core action list."""
    return [
        CoreAction(
            action_id=c["option_id"],
            description=c.get("description", ""),
            dof_delta=list(c.get("projected_dof_delta", {}).items()),
            is_reversible=bool(c.get("is_reversible", True)),
            duration_turns=1.0,
        )
        for c in candidates
    ]


def build_agent(agent_type: str, extractor: GameStateExtractor):
    """Create the agent for a given agent_type."""
    if agent_type == "no-op":
        return NoOpAgent()
    if agent_type == "random":
        return RandomAgent()

    if agent_type.startswith("dof_"):
        strategy_name = agent_type[len("dof_"):]
        strategy = next(
            (s for s in ALL_STRATEGIES if s.name == strategy_name), DEFENSIVE
        )
        gen = HeuristicGenerator(strategy=strategy)
        core = DOFCalculusCore() if HAVE_DOF_CORE else None

        class DofAgent(BaseAgent):
            def act(self, obs, info):
                dof = extractor.extract(obs, info, info.get("turn", 0))
                avail = info.get("available_actions", {})
                cands = gen.generate_candidates(dof.state, avail)
                if not cands:
                    return None

                if core is None:
                    # Python fallback: same objective, no Rust veto.
                    best = gen.select_best(cands, dof.state)
                    return _to_action(best) if best else None

                decision = core.select_best(_core_entities(dof.state), _core_actions(cands))
                if decision.chosen_action_id is None:
                    # Every option had a negative net delta, or was vetoed:
                    # declining to act is the DOF-correct choice.
                    return None

                for cand in cands:
                    if cand["option_id"] == decision.chosen_action_id:
                        return _to_action(cand)
                return None

        return DofAgent()

    return RandomAgent()


def run_match(agent_type: str, turns: int = 30, port: int = 6001,
              timeout: int = 240, seed: int | None = None,
              include_series: bool = False) -> MatchMetrics:
    """Play one game on ``port`` and return its metrics.

    ``seed`` is handed to ``env.reset`` which sets the Freeciv map/game/agent
    seeds, so distinct seeds produce distinct scenarios.
    """
    metrics = MatchMetrics(agent_name=agent_type, include_series=include_series)
    extractor = GameStateExtractor(my_player_id=0)
    env = None

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(timeout)
    try:
        agent = build_agent(agent_type, extractor)

        fc_args["client_port"] = port
        env = gymnasium.make("civrealm/FreecivBase-v0")
        obs, info = env.reset(client_port=port, seed=seed)
        metrics.seed = seed
        metrics.engine = "rust-core" if HAVE_DOF_CORE else "python"

        step = 0
        done = False
        while not done and step < turns:
            action = agent.act(obs, info)

            extraction = extractor.extract(obs, info, info.get("turn", step))
            entities = extraction.state.entities
            non_collapse = [e for e in entities.values() if not e.is_collapse_source]
            dof_index = (
                sum(e.current_dof for e in non_collapse) / len(non_collapse)
                if non_collapse else 0.0
            )
            metrics.record_step(
                info.get("turn", step),
                dof_index,
                len(entities),
                action,
                compute_total_dof_index(extraction.state),
            )

            obs, _reward, terminated, truncated, info = env.step(action)
            done = bool(terminated or truncated)
            step += 1
            if step % 10 == 0:
                print(f" [{step}/{turns}]", end="", flush=True)

        metrics.finished = True
    except MatchTimeout as exc:
        metrics.error = f"timeout: {exc}"
    except Exception as exc:  # noqa: BLE001 - report, never crash the tournament
        metrics.error = f"{type(exc).__name__}: {exc}"
    finally:
        signal.alarm(0)
        if env is not None:
            try:
                env.close()
            except Exception:  # noqa: BLE001
                pass

    return metrics


def _resolve_agent_types(args) -> list[str]:
    agents = ["random", "no-op"] + [f"dof_{s.name}" for s in ALL_STRATEGIES]
    if not args.only.strip():
        return agents
    wanted = [a.strip() for a in args.only.split(",") if a.strip()]
    unknown = [a for a in wanted if a not in agents]
    if unknown:
        print(f"ERROR: unknown agent(s): {', '.join(unknown)}")
        print(f"Available: {', '.join(agents)}")
        sys.exit(2)
    return wanted


def _print_report(agents: list[str], results: dict[str, list[dict]]) -> None:
    print("\n" + "=" * 88)
    print("RESULTS (all agents measured through the same recorder)")
    print("=" * 88)
    print(f"{'Agent':<20}{'N':>4}{'Turns':>7}{'Index':>10}{'AvgDoF':>9}"
          f"{'IrrRat':>8}{'Issued':>8}{'Skipped':>9}{'Errs':>6}")
    print("-" * 88)
    for agent in agents:
        summary = agent_turns(results[agent])
        if summary["n"] == 0:
            print(f"{agent:<20}{0:>4}")
            continue
        print(f"{agent:<20}{summary['n']:>4}{summary['turns']:>7.1f}"
              f"{summary['avg_total_dof_index']:>10.3f}"
              f"{summary['avg_dof']:>9.3f}"
              f"{summary['irreversibility_ratio']:>8.2f}"
              f"{summary['actions_issued']:>8.1f}{summary['skipped_turns']:>9.1f}"
              f"{summary['errors']:>6}")

    for agent in agents:
        for record in results[agent]:
            if record.get("error"):
                print(f"  [error] {agent}: {record['error']}")
                break

    print("\nIrrRat = irreversible / issued actions (skipped turns excluded).")
    print("For N and confidence intervals run: bash do.sh analyze")


def main():
    args = ARGS

    if not args.auto_port:
        last_port = args.port + args.episodes - 1
        if args.port < MIN_PORT or last_port > MAX_PORT:
            print(f"ERROR: slots {args.port}-{last_port} outside {MIN_PORT}-{MAX_PORT}."
                  " Use auto-allocation (default) or lower --episodes.")
            sys.exit(2)

    agents = _resolve_agent_types(args)
    results: dict[str, list[dict]] = {a: [] for a in agents}

    mode = "auto slot allocation" if args.auto_port else f"slots {args.port}-{args.port + args.episodes - 1}"
    total = len(agents) * args.episodes
    print(f"REAL tournament: {len(agents)} agents x {args.episodes} episodes x "
          f"{args.turns} turns  ({total} matches)")
    print(f"Slot mode: {mode}")
    print(f"Per-match timeout: {args.timeout}s, retries: {args.retries}\n")

    started = time.time()
    done_matches = 0

    for agent in agents:
        print(f"  {agent:<20}", end="", flush=True)
        for ep in range(args.episodes):
            seed = None if args.seed_base is None else args.seed_base + ep
            metrics = None
            port = None
            for _attempt in range(args.retries + 1):
                if args.auto_port:
                    port = allocate_port(args.port_wait)
                if port is None:
                    port = args.port + (ep % max(1, MAX_PORT - MIN_PORT + 1))
                metrics = run_match(agent, args.turns, port, args.timeout, seed,
                                    args.save_series)
                if not metrics.error:
                    break
                time.sleep(args.settle)

            results[agent].append(metrics.to_dict())
            done_matches += 1
            tag = "ok" if not metrics.error else "ERR"
            elapsed = time.time() - started
            rate = done_matches / elapsed if elapsed else 0.0
            remaining = (total - done_matches) / rate if rate else 0.0
            print(f" {tag}@{port}", end="", flush=True)
            if done_matches % 5 == 0:
                print(f"  [{done_matches}/{total}  eta {remaining/60:.1f}m]",
                      end="", flush=True)
            time.sleep(args.settle)
        print("")

    _print_report(agents, results)

    if args.output:
        payload = {
            "meta": {
                "agents": agents,
                "episodes": args.episodes,
                "turns": args.turns,
                "timeout": args.timeout,
                "match_timeout_s": args.timeout,
                "save_series": args.save_series,
                "seed_base": args.seed_base,
                "elapsed_s": round(time.time() - started, 1),
            },
            "results": results,
        }
        with open(args.output, "w") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()