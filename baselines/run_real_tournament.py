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
import hashlib
import json
import os
import signal
import sys
import time
import traceback
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
    parser.add_argument("--port-wait", type=int, default=180,
                        help="seconds to wait for a free slot before falling back")
    parser.add_argument("--retries", type=int, default=2,
                        help="extra attempts per match when the server stalls")
    parser.add_argument("--settle", type=float, default=10.0,
                        help="seconds between matches (gives Publite2 time to "
                             "restart a recycled slot before it is reused)")
    parser.add_argument("--pace", type=float, default=0.0,
                        help="seconds to sleep between decisions — use for a slow, "
                             "watchable demo game an observer can join")
    parser.add_argument("--trace", action="store_true",
                        help="print every decision and every turn end, so an observer "
                             "can correlate the agent's play with the map")
    parser.add_argument("--max-decisions-per-turn", type=int, default=20,
                        help="cap decisions issued inside one turn before the turn "
                             "is ended explicitly")
    parser.add_argument("--lookahead", type=int, default=3,
                        help="DOF-Core lookahead horizon in turns (core default 3). "
                             "Cost grows ~ candidates**horizon, so raise it together "
                             "with a smaller --max-candidates.")
    parser.add_argument("--context-switch-penalty", type=float, default=0.5,
                        help="DOF-Core penalty charged to irreversible actions "
                             "(Axiom 4); core default 0.5")
    parser.add_argument("--max-candidates", type=int, default=8,
                        help="max branches handed to DOF-Core per decision")
    parser.add_argument("--seed-base", type=int, default=None,
                        help="if set, episode i calls env.reset(seed=seed_base+i). "
                             "NOTE: observed ineffective on the standard stand -- "
                             "Publite2 creates the game (and its map) before the "
                             "client connects, so episodes repeat the SAME scenario. "
                             "Confidence intervals are therefore within-scenario, "
                             "not across environments.")
    parser.add_argument("--only", type=str, default="",
                        help="comma-separated agent subset, e.g. random,dof_defensive")
    parser.add_argument("--no-curiosity", dest="curiosity", action="store_false",
                        default=True,
                        help="A/B: turn OFF the bonus for probing unmeasured "
                             "actions (env.config.CURIOSITY_ENABLED). Everything "
                             "else stays identical, so a difference is the "
                             "mechanism's own effect.")
    parser.add_argument("--false-claim", type=str, default="",
                        help="заведомо неверное утверждение в модель перед матчем, "
                             "KEY=VALUE[,KEY=VALUE…]; проверяет, что мир его "
                             "исправит (Axiom «реальность первична»). Пример: "
                             "--false-claim rules.citymindist=3.0")
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

from env import config as env_config
from env.config import AXIOM4_PENALTY_OPTIONS, CORE_DOF_SCALE
from env.entity_extractor import GameStateExtractor, as_dict, compute_total_dof_index
from env.experiments import note_choice
from env.wedged import record_wedged
from env.world_model import FALSE_CLAIM_MARKER
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

#: Сколько секунд ждать один шаг, прежде чем считать, что стенд заклинило.
#: Измерено, что `irrigation` на речной равнине и `build_road` на орошённой
#: равнине не возвращают управление из `env.step` вообще — без этого таймера
#: матч умирает только по общему бюджету, и непонятно, какой выбор его убил.
STEP_TIMEOUT = 20


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


def allocate_port(wait: int = 120, bad_slots: set | None = None):
    """Ask civrealm for a free slot, or None if none appears in ``wait`` seconds.

    ``Ports.get()`` loops forever when no slot is free, so it is alarm-guarded.
    Slots are recycled by Publite2 after a game ends, so waiting is normal in a
    long run.

    ``bad_slots`` are ports that already failed a match in this process. CivRealm
    releases a slot when it has been idle for 30s even if its game never actually
    restarted, and such a slot hangs (`BeginTurnTimeout`); re-drawing it wastes a
    full match timeout, so failed slots are skipped. Drawing again is safe because
    ``Ports.get()`` marks the slot it just handed out as occupied.
    """
    try:
        from civrealm.freeciv.utils.port_utils import Ports
    except Exception:  # noqa: BLE001 - status endpoint unreachable
        return None

    def _alarm(signum, frame):
        raise MatchTimeout("no free slot")

    bad = bad_slots or set()
    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(max(1, wait))
    try:
        for _ in range(8):
            port = Ports.get()
            if port not in bad:
                return port
        return None
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
    """SystemStateMatrix → Rust core entity list.

    The core carries `current_dof` in the DOF-SPEC [0, 1] field range (its
    `apply_action` clamps at 1.0), while the extractor works in options. Every
    value the core sees is therefore divided by one shared reference, so the
    ordering and the sign of every net delta are identical to the option-space
    computation (Σ ln(x/c) = Σ ln(x) − n·ln c, and n is the same on both sides of
    every comparison the bridge makes).
    """
    return [
        CoreEntity(
            entity_id=e.entity_id,
            current_dof=min(1.0, e.dof_count / CORE_DOF_SCALE),
            is_collapse_source=e.is_collapse_source,
            is_reversible=e.time_to_collapse_mks > 1e14,
        )
        for e in state.entities.values()
    ]


def _core_actions(candidates: list[dict]) -> list:
    """DOF candidates → Rust core action list (deltas in the core's own units)."""
    return [
        CoreAction(
            action_id=c["option_id"],
            description=c.get("description", ""),
            dof_delta=[(k, v / CORE_DOF_SCALE)
                       for k, v in c.get("projected_dof_delta", {}).items()],
            is_reversible=bool(c.get("is_reversible", True)),
            duration_turns=1.0,
        )
        for c in candidates
    ]


def build_agent(agent_type: str, extractor: GameStateExtractor,
                lookahead: int = 3, context_switch_penalty: float = 0.5,
                max_candidates: int = 8, trace: bool = False):
    """Create the agent for a given agent_type.

    ``lookahead`` / ``context_switch_penalty`` configure the DOF-Core engine;
    ``max_candidates`` caps how many branches each decision is evaluated over
    (the core's lookahead cost grows roughly as ``candidates ** horizon``).
    """
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
        gen.max_candidates = max_candidates
        core = (
            DOFCalculusCore(
                lookahead_horizon=lookahead,
                # The penalty is configured in options (the unit every delta is
                # projected in) and converted into the core's own scale, so it
                # stays comparable with the deltas it is weighed against.
                context_switch_penalty=context_switch_penalty / CORE_DOF_SCALE,
            )
            if HAVE_DOF_CORE else None
        )

        class DofAgent(BaseAgent):
            def act(self, obs, info):
                dof = extractor.extract(obs, info, info.get("turn", 0))
                avail = info.get("available_actions", {})
                cands = gen.generate_candidates(dof.state, avail)
                if not cands:
                    return None

                if trace and cands:
                    preview = " ".join(
                        f"{c['action_name']}({sum(c['projected_dof_delta'].values()):+.2f}"
                        f"{',rev' if c['is_reversible'] else ',IRR'})"
                        for c in cands[:6]
                    )
                    print(f"        candidates: {preview}", flush=True)

                if core is None:
                    # Python fallback: same objective, no Rust veto.
                    best = gen.select_best(cands, dof.state)
                    return _to_action(best) if best else None

                decision = core.select_best(_core_entities(dof.state), _core_actions(cands))
                if decision.chosen_action_id is None or decision.net_delta <= 0:
                    # DOF-SPEC Decision Calculus §4: select a path only if its
                    # projected gain STRICTLY exceeds the transition cost
                    # (NetDelta > 0). Accepting net_delta == 0 let the agent spend
                    # whole games on measured-neutral actions (irrigation/road on
                    # one unit, forever) because a zero-gain option was always
                    # available and the core only declined on negative deltas.
                    if trace and decision.chosen_action_id is not None:
                        print(f"        declined {decision.chosen_action_id} "
                              f"(net_delta={decision.net_delta:+.3f} <= 0)", flush=True)
                    return None

                for cand in cands:
                    if cand["option_id"] == decision.chosen_action_id:
                        return _to_action(cand)
                return None

        return DofAgent()

    return RandomAgent()


def _turn_phase(action, used_actors: set, decisions_this_turn: int,
                max_decisions: int) -> tuple[str, tuple | None]:
    """Decide whether to act or to end the turn.

    CivRealm ends a turn **only** when the action handed to ``env.step`` is
    ``None`` (``civ_controller.perform_action``); a real action never advances
    the turn. Without this bookkeeping an agent that always finds something to do
    plays the whole match inside turn 1 and the AI opponents never move — which
    made a no-op baseline look like the strongest strategy.

    Returns ``("act", key)`` or ``("end_turn", None)``.
    """
    if action is None:
        return "end_turn", None
    if decisions_this_turn >= max_decisions:
        return "end_turn", None

    key = (action[0], action[1])
    if key in used_actors:
        # One decision per actor per turn (civrealm's own convention): without
        # this, a reversible action with a positive-looking projection is
        # repeated forever inside a single turn.
        return "end_turn", None
    return "act", key


def _start_footprint(obs: dict) -> tuple[str, dict]:
    """Отпечаток СТАРТА: где мы появились и что видно с этой точки.

    Почему не «отпечаток карты». На 1-м ходу разведано 9 клеток из 4056, а
    неразведанные помечены 255 — то есть слой террейна почти постоянный, и
    осреднение по блокам даёт одинаковый хэш у РАЗНЫХ миров. Именно так и вышло:
    «одинаковый отпечаток» у двух слотов оказался артефактом вырожденного
    инструмента, а не совпадением карт.

    Измерено: три прогона на ОДНОМ слоте дали три разных старта ((7,43),
    (21,11), (42,29)). Значит, каждый матч — своя среда, и «пара по слоту» не
    существует: сравнивать можно только распределения по многим матчам.
    Отпечаток старта фиксирует это: по нему видно, действительно ли две выборки
    сделаны из одного места, а не предположительно.

    `DOF_DUMP_MAP` кладёт слои на диск для разбора.
    """
    layer_map = as_dict(obs.get('map')) or {}
    dump = os.environ.get("DOF_DUMP_MAP", "")
    digest = hashlib.sha1()
    info: dict[str, Any] = {"revealed": 0, "start": None}
    try:
        import numpy as np
        terrain = layer_map.get('terrain')
        output = layer_map.get('output')
        if output is not None:
            arr_out = np.ascontiguousarray(output)
            if dump:
                np.save(f"{dump}.output.npy", arr_out)
            # Разведано там, где выход ненулевой (у нераскрытой клетки выход 0).
            mask = arr_out.sum(axis=2) > 0
            ys, xs = np.nonzero(mask)
            info["revealed"] = int(mask.sum())
            if len(ys):
                info["start"] = [int(round(ys.mean())), int(round(xs.mean()))]
            digest.update(mask.tobytes())
            digest.update(arr_out[mask].tobytes())
        if terrain is not None:
            arr_t = np.ascontiguousarray(terrain)
            if dump:
                np.save(f"{dump}.terrain.npy", arr_t)
            digest.update(arr_t.shape.__repr__().encode())
            if info["revealed"]:
                digest.update(arr_t[mask].tobytes())
    except Exception:  # noqa: BLE001 - отпечаток не стоит падения матча
        digest.update(repr(sorted(layer_map)).encode())
    if dump:
        try:
            with open(f"{dump}.fingerprint", "w") as fh:
                json.dump({"start_footprint": digest.hexdigest()[:12], **info},
                          fh, ensure_ascii=False)
        except OSError:
            pass
    return digest.hexdigest()[:12], info


def _count_actions(obs: dict) -> int:
    """Сколько действий сервер реально предложил в этом наблюдении.

    Значение `available_actions[ctrl][actor][name]` истинно, если действие
    доступно (CivRealm удаляет невалидные). Ноль здесь — это не «агент решил
    ничего не делать», а «действий не дали»: такую разницу надо видеть числом,
    а не выводить из косвенных признаков.
    """
    avail = as_dict(obs.get('available_actions')) or {}
    count = 0
    for ctrl_map in avail.values():
        for actor_map in as_dict(ctrl_map).values():
            for value in as_dict(actor_map).values():
                try:
                    if bool(value):
                        count += 1
                except Exception:  # noqa: BLE001 - numpy-скаляр и т.п.
                    count += 1
    return count


def _parse_false_claims(spec: str) -> list[tuple[str, float]]:
    """`rules.citymindist=3.0,rules.food_cost=4` → [(key, 3.0), (key, 4.0)]."""
    out: list[tuple[str, float]] = []
    for item in str(spec or "").split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, _, raw = item.partition("=")
        try:
            out.append((key.strip(), float(raw)))
        except ValueError:
            print(f"  [warn] не разобрал неверное утверждение: {item}", flush=True)
    return out


def _record_wedge(metrics: MatchMetrics, action, turn: int) -> None:
    """Записать выбор, о который заклинило стенд, — это измерение, а не шум.

    Матч потерян, но знание остаётся: семейство уходит в реестр, и следующий
    матч (в т.ч. следующий агент того же прогона) за него уже не заплатит и не
    выберет его.
    """
    if action is None:
        return
    ctrl, name = str(action[0]), str(action[2])
    metrics.wedge_action = {"ctrl_type": ctrl, "action_name": name, "turn": turn}
    try:
        record_wedged(ctrl, name, turn=turn, context={"agent": metrics.agent_name})
    except OSError as exc:  # pragma: no cover - диск, а не логика
        print(f"  [warn] не записал клинч {ctrl}/{name}: {exc}", flush=True)


def run_match(agent_type: str, turns: int = 30, port: int = 6001,
              timeout: int = 240, seed: int | None = None,
              include_series: bool = False, max_decisions_per_turn: int = 20,
              lookahead: int = 3, context_switch_penalty: float = 0.5,
              max_candidates: int = 8, pace: float = 0.0, trace: bool = False,
              curiosity: bool = True,
              false_claims: list[tuple[str, float]] | None = None,
              ) -> MatchMetrics:
    """Play one game on ``port`` and return its metrics, one record per turn.

    ``turns`` counts *game turns*, not decisions: within a turn the agent may
    issue several decisions (one per actor), then the turn is ended explicitly by
    stepping ``None``.

    ``seed`` is handed to ``env.reset`` which sets the Freeciv map/game/agent
    seeds, so distinct seeds produce distinct scenarios.
    """
    metrics = MatchMetrics(agent_name=agent_type, include_series=include_series)
    metrics.curiosity = curiosity
    metrics.port = port
    # The A/B switch: read at every bonus call, so it takes effect per match.
    env_config.CURIOSITY_ENABLED = curiosity
    extractor = GameStateExtractor(my_player_id=0)
    env = None

    # Deliberately wrong claims, if the caller asked for them: the point is to make
    # the world correct something, because on live data it mostly *adds* facts
    # rather than contradicting them — so the correction branch would never be
    # exercised and "reality is primary" would stay an untested belief.
    for key, value in (false_claims or []):
        extractor.model.plant_false_claim(key, value, note="внедрено раннером")
        metrics.false_claims.append(f"{key}={value}")

    signal.signal(signal.SIGALRM, _on_alarm)
    deadline = time.time() + timeout
    signal.alarm(timeout)
    try:
        agent = build_agent(agent_type, extractor, lookahead,
                           context_switch_penalty, max_candidates, trace)

        fc_args["client_port"] = port
        env = gymnasium.make("civrealm/FreecivBase-v0")
        obs, info = env.reset(client_port=port, seed=seed)

        # Which civilisation the env is playing is decided when the game is
        # created, NOT by the agent — hardcoding player 0 silently made every
        # own-civilisation test fail (garrison counts, the founding estimate, and
        # therefore whether expansion looked like a gain at all).
        try:
            extractor.my_player_id = env.get_playerid()
        except Exception:  # noqa: BLE001 - the id is optional context, not a blocker
            pass
        metrics.seed = seed
        metrics.engine = "rust-core" if HAVE_DOF_CORE else "python"

        turns_played = 0
        decisions_this_turn = 0
        used_actors: set = set()
        done = False

        while not done and turns_played < turns:
            if pace:
                time.sleep(pace)
            # Every step is bounded. A step that never returns is not a slow stand,
            # it is a wedge: knowing WHICH pick wedged it is the whole point, and
            # the global match timeout alone cannot tell us that.
            stepped = False
            try:
                remaining = max(1.0, deadline - time.time())
                step_budget = min(STEP_TIMEOUT, remaining)
                signal.setitimer(signal.ITIMER_REAL, step_budget)
                if _count_actions(obs) == 0:
                    # Not (necessarily) a defect: with no action left to offer the
                    # loop ends the turn, and that is how a turn normally closes.
                    # A defect is zero actions for the WHOLE match; this counter is
                    # context for reading that, not a verdict by itself.
                    metrics.empty_action_turns += 1
                action = agent.act(obs, info)
                phase, key = _turn_phase(action, used_actors, decisions_this_turn,
                                         max_decisions_per_turn)

                if phase == "act":
                    used_actors.add(key)
                    decisions_this_turn += 1
                    end_turn = False
                    metrics.record_decision(turns_played + 1, action)
                    if trace:
                        print(f"      turn {turns_played + 1}: "
                              f"{action[0]}/{action[1]}/{action[2]}", flush=True)
                else:
                    end_turn = True
                    action = None  # stepping None is what ends the turn
                    decisions_this_turn = 0
                    used_actors = set()

                stepped = True  # from here a hang belongs to the chosen action
                obs, _reward, terminated, truncated, info = env.step(action)
            except MatchTimeout as exc:
                if not stepped or step_budget < STEP_TIMEOUT - 1e-6:
                    # Either the match budget ran out, or the agent itself hung:
                    # neither names an action, so there is nothing to measure.
                    raise
                _record_wedge(metrics, action, turns_played + 1)
                raise MatchTimeout(
                    f"wedged on {action[0]}/{action[2]} at turn "
                    f"{turns_played + 1}") from exc
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)

            done = bool(terminated or truncated)
            # An experiment counts when the action was actually TAKEN, not when it
            # was chosen: a pick the server rejects teaches nothing, and the bonus
            # for probing must decay against real experience only.
            if action is not None and not end_turn:
                note_choice(extractor.model, str(action[0]), str(action[2]),
                            turn=turns_played + 1)

            if end_turn:
                turns_played += 1
                extraction = extractor.extract(obs, info, info.get("turn", turns_played))
                if not metrics.start_fingerprint:
                    # Captured on the first turn. Not "the map": at turn 1 only a
                    # handful of tiles are revealed, so what identifies a match is
                    # where we started, not a map we cannot see.
                    (metrics.start_fingerprint,
                     start_info) = _start_footprint(obs)
                    metrics.revealed_cells = start_info.get("revealed", 0)
                    metrics.start_xy = start_info.get("start")
                entities = extraction.state.entities
                non_collapse = [e for e in entities.values() if not e.is_collapse_source]
                dof_index = (
                    sum(e.current_dof for e in non_collapse) / len(non_collapse)
                    if non_collapse else 0.0
                )
                # One record per turn; the "action" is the end-turn marker, and the
                # per-decision reversibility accounting is kept in decisions_*.
                metrics.record_step(
                    turns_played,
                    dof_index,
                    len(entities),
                    None,
                    compute_total_dof_index(extraction.state),
                )
                if turns_played % 10 == 0:
                    index = compute_total_dof_index(extraction.state)
                    print(f" [turn {turns_played}/{turns} ent={len(entities)} "
                          f"idx={index:.2f}]", end="", flush=True)

        metrics.finished = True
    except MatchTimeout as exc:
        metrics.error = f"timeout: {exc}"
    except Exception as exc:  # noqa: BLE001 - report, never crash the tournament
        metrics.error = f"{type(exc).__name__}: {exc}"
        # A one-line summary is what the report shows; the traceback is what
        # makes the failure fixable, so keep it right next to the match.
        print(traceback.format_exc(), file=sys.stderr, flush=True)
    finally:
        signal.alarm(0)
        # Knowledge gained is reported even when the match died: a wedged match
        # that still taught us a family's effect is not a total loss, and the A/B
        # needs the count to compare "learning" against "score".
        try:
            metrics.experiments_total = sum(extractor.model.experiment_attempts.values())
            metrics.pairs_total = sum(len(v) for v in extractor.model.pairs.values())
            metrics.experiment_families = dict(extractor.model.experiment_attempts)
            # Did the world correct us? Counted from the model's own log, so the
            # answer is a number, not an impression.
            verdicts: dict[str, int] = {}
            corrected: list[str] = []
            log: list[dict] = []
            for rec in extractor.model.reconciliations:
                # Our own injection is not a world correction: it *is* the record
                # whose prior was the honest value and whose observed value is the
                # lie we planted. Counting it would double the evidence.
                if FALSE_CLAIM_MARKER in (rec.evidence or ""):
                    continue
                verdicts[rec.verdict] = verdicts.get(rec.verdict, 0) + 1
                if rec.verdict == 'corrected':
                    if rec.key not in corrected:
                        corrected.append(rec.key)
                    log.append({'key': rec.key, 'turn': rec.turn,
                                'prior': rec.prior, 'observed': rec.observed,
                                'source': getattr(rec.source, 'value', str(rec.source))})
            metrics.reconciled = verdicts
            metrics.corrected_keys = corrected
            metrics.correction_log = log
        except AttributeError:  # pragma: no cover - модель без учёта пар
            pass
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
          f"{'IrrRat':>8}{'Dec/turn':>9}{'SkipTurn':>9}{'Errs':>6}")
    print("-" * 88)
    for agent in agents:
        summary = agent_turns(results[agent])
        if summary["n"] == 0:
            print(f"{agent:<20}{0:>4}")
            continue
        records = results[agent]
        dec_per_turn = sum(r.get("decisions_per_turn_mean", 0.0) for r in records) / len(records)
        print(f"{agent:<20}{summary['n']:>4}{summary['turns']:>7.1f}"
              f"{summary['avg_total_dof_index']:>10.3f}"
              f"{summary['avg_dof']:>9.3f}"
              f"{summary['irreversibility_ratio']:>8.2f}"
              f"{dec_per_turn:>9.1f}{summary['skipped_turns']:>9.1f}"
              f"{summary['errors']:>6}")

    for agent in agents:
        for record in results[agent]:
            if record.get("error"):
                print(f"  [error] {agent}: {record['error']}")
                break

    # Reconciliation is the point of the model being alive: show what the world
    # said about our claims, including whether it corrected anything.
    for agent in agents:
        for record in results[agent]:
            verdicts = record.get("reconciled") or {}
            if not verdicts:
                continue
            corrected = record.get("corrected_keys") or []
            claims = record.get("false_claims") or []
            if claims or corrected:
                print(f"  [model] {agent}: сверки {verdicts}"
                      + (f", ИСПРАВЛЕНО {corrected}" if corrected else "")
                      + (f", внедрено неверного: {claims}" if claims else ""))

    print("\nOne row per agent; Turn = game turns actually played (an agent that never")
    print("hands None to env.step never advances the game — see _turn_phase).")
    print("IrrRat = irreversible / decisions; SkipTurn = turns with no decision.")
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
    print(f"Curiosity bonus (probing unmeasured actions): "
          f"{'ON' if args.curiosity else 'OFF'}")
    print(f"Per-match timeout: {args.timeout}s (per step {STEP_TIMEOUT}s), "
          f"retries: {args.retries}\n")

    started = time.time()
    done_matches = 0

    bad_slots: set = set()
    consecutive_errors = 0
    for agent in agents:
        print(f"  {agent:<20}", end="", flush=True)
        for ep in range(args.episodes):
            seed = None if args.seed_base is None else args.seed_base + ep
            metrics = None
            port = None
            for _attempt in range(args.retries + 1):
                if args.auto_port:
                    port = allocate_port(args.port_wait, bad_slots)
                if port is None:
                    port = args.port + (ep % max(1, MAX_PORT - MIN_PORT + 1))
                metrics = run_match(agent, args.turns, port, args.timeout, seed,
                                    args.save_series, args.max_decisions_per_turn,
                                    args.lookahead, args.context_switch_penalty,
                                    args.max_candidates, args.pace, args.trace,
                                    args.curiosity,
                                    _parse_false_claims(args.false_claim))
                if not metrics.error:
                    consecutive_errors = 0
                    break
                bad_slots.add(port)
                consecutive_errors += 1
                # If many slots in a row die, reset the pool so Publite2
                # can recycle them (BeginTurnTimeout / stale slots).
                if consecutive_errors >= 3:
                    try:
                        from civrealm.freeciv.utils.port_utils import Ports
                        Ports.clear()
                        consecutive_errors = 0
                    except Exception:  # noqa: BLE001
                        pass
                metrics.error = f"{metrics.error} [slot {port}]"
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
                "step_timeout_s": STEP_TIMEOUT,
                "curiosity": args.curiosity,
                "false_claim": args.false_claim,
                "lookahead": args.lookahead,
                "context_switch_penalty": args.context_switch_penalty,
                "max_candidates": args.max_candidates,
                "max_decisions_per_turn": args.max_decisions_per_turn,
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