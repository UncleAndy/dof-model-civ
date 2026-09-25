#!/usr/bin/env python3
"""
Real CivRealm tournament runner.

Plays actual games against a running Freeciv-web server (docker compose),
so agent actions genuinely affect the game state. Compares the DOF agent
strategies against random / no-op baselines.

Usage:
    bash do.sh real-tournament --episodes 3 --turns 50 --port 6001

Notes
-----
* CivRealm agent ports live in 6000-6009; keep ``port + episodes - 1 <= 6009``.
* Gymnasium's passive env checker emits noisy warnings for CivRealm's
  non-standard observation space - they are silenced here on purpose.
* Each match is guarded by a wall-clock alarm so a stuck server connection
  cannot hang the whole tournament.
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
# so our CLI has to be resolved *before* civrealm is imported and the leftover
# arguments handed back to it untouched.
def _parse_cli(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_real_tournament.py",
        description="Real CivRealm tournament (agents play actual games).",
    )
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--turns", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=240,
                        help="per-match wall-clock budget in seconds")
    parser.add_argument("--port", type=int, default=6001,
                        help="base port; used for the first match when --no-auto-port")
    parser.add_argument("--auto-port", dest="auto_port", action="store_true",
                        default=True,
                        help="pick a free multiplayer port via civrealm Ports.get() "
                             "(default)")
    parser.add_argument("--no-auto-port", dest="auto_port", action="store_false",
                        help="use --port + episode index instead of auto-allocation")
    parser.add_argument("--port-wait", type=int, default=30,
                        help="seconds to wait for a free port before falling back")
    parser.add_argument("--retries", type=int, default=1,
                        help="extra attempts per match when the server times out")
    parser.add_argument("--only", type=str, default="",
                        help="comma-separated agent subset, e.g. random,dof_defensive")
    parser.add_argument("--output", type=str)
    args, rest = parser.parse_known_args(argv)
    # Let civrealm's parser see only the arguments it knows about.
    sys.argv = [sys.argv[0]] + rest
    return args


ARGS = _parse_cli(sys.argv[1:])

import gymnasium
from civrealm.configs import fc_args
from civrealm.agents import RandomAgent, BaseAgent

from env.entity_extractor import GameStateExtractor
from brain.generator.heuristics import ALL_STRATEGIES, DEFENSIVE, HeuristicGenerator

MIN_PORT = 6000
MAX_PORT = 6009


class MatchTimeout(Exception):
    """Raised when a single match exceeds its wall-clock budget."""


def _on_alarm(signum, frame):  # pragma: no cover - signal path
    raise MatchTimeout("match exceeded wall-clock budget")


class NoOpAgent(BaseAgent):
    """Baseline that never issues an action."""

    def act(self, observations, info):
        return None


class MatchResult:
    def __init__(self, name: str = ""):
        self.agent_name = name
        self.turns_played = 0
        self.dof_series: list[float] = []
        self.entity_series: list[int] = []
        self.irr_actions = 0
        self.total_actions = 0
        self.error = ""

    @property
    def avg_dof(self) -> float:
        return sum(self.dof_series) / len(self.dof_series) if self.dof_series else 0.0

    @property
    def min_ent(self) -> int:
        return min(self.entity_series) if self.entity_series else 0

    @property
    def max_ent(self) -> int:
        return max(self.entity_series) if self.entity_series else 0

    @property
    def irr_ratio(self) -> float:
        return self.irr_actions / self.total_actions if self.total_actions else 0.0


def _to_action(candidate: dict):
    """Convert a DOF candidate into the (ctrl_type, actor_id, action_name) tuple.

    The candidate carries its origin as structured fields, so nothing has to be
    parsed back out of ``option_id`` (actor ids and action names may contain
    underscores, and actor ids may be ints or strings).
    """
    ctrl_type = candidate.get('ctrl_type')
    actor_id = candidate.get('actor_id')
    action_name = candidate.get('action_name')
    if ctrl_type is None or actor_id is None or action_name is None:
        return None
    return (ctrl_type, actor_id, action_name)


def _build_agent(agent_type: str, result: MatchResult, extractor: GameStateExtractor):
    """Create the agent for a given agent_type; returns (label, agent)."""
    if agent_type == "random":
        return "random", RandomAgent()
    if agent_type == "no-op":
        return "no-op", NoOpAgent()

    if agent_type.startswith("dof_"):
        strategy_name = agent_type[len("dof_"):]
        strategy = next(
            (s for s in ALL_STRATEGIES if s.name == strategy_name), DEFENSIVE
        )
        gen = HeuristicGenerator(strategy=strategy)

        class DofAgent(BaseAgent):
            def act(self, obs, info):
                dof = extractor.extract(obs, info, info.get("turn", 0))
                state = dof.state
                avail = info.get("available_actions", {})

                best = None
                cands = gen.generate_candidates(state, avail)
                if cands:
                    best = gen.select_best(cands, state)

                if best is None:
                    return None

                action = _to_action(best)
                if action is None:
                    return None

                if not best.get("is_reversible", True):
                    result.irr_actions += 1
                result.total_actions += 1
                return action

        return agent_type, DofAgent()

    return "random", RandomAgent()


def allocate_port(wait: int = 30):
    """Ask civrealm for a free multiplayer port, or None if none appears.

    ``Ports.get()`` loops forever when the server has no idle slot, so it is
    wrapped in a wall-clock alarm to keep the tournament responsive.
    """
    try:
        from civrealm.freeciv.utils.port_utils import Ports
    except Exception:  # noqa: BLE001 - server status unreachable
        return None

    def _alarm(signum, frame):
        raise MatchTimeout("no free port")

    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(max(1, wait))
    try:
        return Ports.get()
    except MatchTimeout:
        return None
    except Exception:  # noqa: BLE001
        return None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def run_match(agent_type: str, turns: int = 50, port: int = 6001,
              timeout: int = 240) -> MatchResult:
    """Play one game on ``port`` and return its metrics."""
    result = MatchResult(agent_type)
    extractor = GameStateExtractor(my_player_id=0)
    env = None

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(timeout)
    try:
        _, agent = _build_agent(agent_type, result, extractor)

        fc_args["client_port"] = port
        env = gymnasium.make("civrealm/FreecivBase-v0")
        obs, info = env.reset(client_port=port)

        step = 0
        done = False
        while not done and step < turns:
            action = agent.act(obs, info)

            dr = extractor.extract(obs, info, info.get("turn", step))
            non_collapse = [e for e in dr.state.entities.values()
                            if not e.is_collapse_source]
            if non_collapse:
                result.dof_series.append(
                    sum(e.current_dof for e in non_collapse) / len(non_collapse)
                )
            result.entity_series.append(len(dr.state.entities))

            obs, _reward, terminated, truncated, info = env.step(action)
            done = bool(terminated or truncated)
            step += 1
            if step % 10 == 0:
                print(f" [{step}/{turns}]", end="", flush=True)

        result.turns_played = step
    except MatchTimeout as exc:
        result.error = f"timeout: {exc}"
    except Exception as exc:  # noqa: BLE001 - report, never crash the tournament
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        signal.alarm(0)
        if env is not None:
            try:
                env.close()
            except Exception:  # noqa: BLE001
                pass

    return result


def main():
    args = ARGS

    last_port = args.port + args.episodes - 1
    if not args.auto_port and (args.port < MIN_PORT or last_port > MAX_PORT):
        print(f"ERROR: ports {args.port}-{last_port} outside the published range "
              f"{MIN_PORT}-{MAX_PORT}. Lower --episodes, shift --port, or use "
              f"auto-allocation (default).")
        sys.exit(2)

    agents = ["random", "no-op"] + [f"dof_{s.name}" for s in ALL_STRATEGIES]
    if args.only.strip():
        wanted = [a.strip() for a in args.only.split(",") if a.strip()]
        unknown = [a for a in wanted if a not in agents]
        if unknown:
            print(f"ERROR: unknown agent(s): {', '.join(unknown)}")
            print(f"Available: {', '.join(agents)}")
            sys.exit(2)
        agents = wanted
    results: dict[str, list[MatchResult]] = {}

    mode = "auto port allocation" if args.auto_port else f"ports {args.port}-{last_port}"
    print(f"REAL tournament: {len(agents)} agents x {args.episodes} eps x "
          f"{args.turns} turns")
    print(f"Port mode: {mode}")
    print(f"Per-match timeout: {args.timeout}s, retries: {args.retries}\n")

    for agent in agents:
        print(f"  {agent:<20}", end="", flush=True)
        results[agent] = []
        for ep in range(args.episodes):
            attempts = args.retries + 1
            r = None
            for attempt in range(attempts):
                port = None
                if args.auto_port:
                    port = allocate_port(args.port_wait)
                if port is None:
                    port = args.port + (ep % max(1, MAX_PORT - MIN_PORT + 1))
                r = run_match(agent, args.turns, port, args.timeout)
                if not r.error:
                    break
                # A dead/already-used port raises a begin-turn timeout: try a
                # different port instead of burning the whole episode.
                time.sleep(2)
            results[agent].append(r)
            tag = "ok" if not r.error else "ERR"
            print(f" {tag}@{port}", end="", flush=True)
            time.sleep(2)  # let the freeciv server release the previous session
        print("")

    print("\n" + "=" * 72)
    print("RESULTS")
    print("=" * 72)
    print(f"{'Agent':<20}{'Turns':>7}{'AvgDoF':>9}{'MinEnt':>8}"
          f"{'MaxEnt':>8}{'IrrRat':>8}{'Errs':>6}")
    print("-" * 72)

    for agent in agents:
        rs = results[agent]
        n = max(len(rs), 1)
        avg_t = sum(r.turns_played for r in rs) / n
        avg_d = sum(r.avg_dof for r in rs) / n
        min_e = min((r.min_ent for r in rs), default=0)
        max_e = max((r.max_ent for r in rs), default=0)
        avg_i = sum(r.irr_ratio for r in rs) / n
        errs = sum(1 for r in rs if r.error)
        print(f"{agent:<20}{avg_t:>7.1f}{avg_d:>9.3f}{min_e:>8}"
              f"{max_e:>8}{avg_i:>8.2f}{errs:>6}")

    # Surface the first error of each failing agent so problems are visible.
    for agent in agents:
        for r in results[agent]:
            if r.error:
                print(f"  [error] {agent}: {r.error}")
                break

    if args.output:
        data = {
            agent: [
                {
                    "turns": r.turns_played,
                    "avg_dof": r.avg_dof,
                    "min_entities": r.min_ent,
                    "max_entities": r.max_ent,
                    "irreversible_ratio": r.irr_ratio,
                    "error": r.error,
                }
                for r in results[agent]
            ]
            for agent in agents
        }
        with open(args.output, "w") as fh:
            json.dump(data, fh, indent=2)
        print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()