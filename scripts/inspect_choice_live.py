#!/usr/bin/env python
"""Живая проверка решения: выбирает ли ядро перемещение к лучшей площадке?

Повторяет путь решения настоящего DOF-агента (извлечение → кандидаты →
дельты бриджа → ядро DOF-Core), без обвязки BaseAgent, чтобы видеть выбор:
площадку носителя, цену перехода, выбранное ядром действие и то, как носитель
действительно двигается к цели.

    python scripts/inspect_choice_live.py --turns 5 --per-turn 3
"""
import argparse
import os
import signal
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)


class MatchTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise MatchTimeout("match exceeded budget")


def describe(ex, obs, info, turn):
    """Напечатать площадку носителей и цену перехода."""
    from env.entity_extractor import is_population_carrier

    state = ex.extract(obs, info, turn).state
    bridge = state.bridge
    carriers = {uid: u for uid, u in (obs.get("unit") or {}).items()
                if isinstance(u, dict) and is_population_carrier(u)}
    pos = ", ".join(f"u{uid}@({u.get('x')},{u.get('y')})" for uid, u in carriers.items())
    gains = {k: round(v, 3) for k, v in bridge.site_move_gain_by_unit.items()}
    work = {k: {e: round(v, 3) for e, v in d.items()}
            for k, d in bridge.terrain_work_gain_by_unit.items()}
    opts = {k: (rep.get("coastal"), rep.get("resource_types"), rep.get("option_bonus"))
            for k, rep in bridge.site_report.items()}
    print(f"\nturn {turn}: носители {pos or '—'}")
    print(f"  селиться можно: {list(bridge.new_city_options_by_unit)}; "
          f"вырезано гейтом: {bridge.nonviable_carrier_sites}; "
          f"цена перехода: {gains or '—'}")
    print(f"  опции площадки (берег, ресурсы, бонус): {opts or '—'}")
    print(f"  цена работ: {work or '— (не измерено)'}")
    return state


def decide(env, gen, heuristic_gen, core, state, avail, obs, info):
    """Выбрать действие ядром и сделать шаг."""
    from dof_core import CoreAction, CoreEntity

    candidates = (heuristic_gen.generate_candidates(state, avail)
                  or gen.generate_from_state(state, avail))
    if not candidates:
        print("  кандидатов нет")
        return obs, info
    core_entities = [
        CoreEntity(entity_id=e.entity_id, current_dof=e.current_dof,
                   is_collapse_source=e.is_collapse_source,
                   is_reversible=e.time_to_collapse_mks < 1e14)
        for e in state.entities.values()
    ]
    core_actions = [
        CoreAction(action_id=c["option_id"], description=c.get("description", ""),
                   dof_delta=list(c.get("projected_dof_delta", {}).items()),
                   is_reversible=c.get("is_reversible", True),
                   duration_turns=c.get("estimated_duration_mks", 5_000_000) / 5_000_000)
        for c in candidates
    ]
    decision = core.select_best(core_entities, core_actions)
    chosen_id = getattr(decision, "chosen_action_id", None)
    chosen = next((c for c in candidates if c["option_id"] == chosen_id), None)
    if chosen is None:
        print("  ядро не выбрало действие (вето или всё невыгодно)")
        return obs, info
    ctrl = chosen.get("ctrl_type") or chosen.get("controller")
    actor = chosen.get("actor_id")
    name = chosen.get("action_name") or chosen.get("name")
    print(f"  ВЫБОР: {ctrl} {actor} {name} "
          f"(дельта {chosen.get('projected_dof_delta')}, "
          f"обратимо {chosen.get('is_reversible')})")
    obs, _r, term, trunc, info = env.step((ctrl, actor, name))
    return obs, info


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--turns", type=int, default=5)
    p.add_argument("--per-turn", type=int, default=3)
    p.add_argument("--strategy", default="expansionist")
    args = p.parse_args()

    import warnings
    warnings.filterwarnings("ignore")
    os.environ["PYTHONWARNINGS"] = "ignore"

    from env.action_mapper import ActionOptionGenerator
    from env.entity_extractor import GameStateExtractor
    from brain.generator.heuristics import ALL_STRATEGIES, DEFENSIVE, HeuristicGenerator

    try:
        from dof_core import DOFCalculusCore
    except ImportError as exc:
        print(f"ERR: rust core unavailable: {exc}")
        raise SystemExit(4)

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(560)
    try:
        from civrealm.freeciv.utils.port_utils import Ports
        import gymnasium
        from civrealm.configs import fc_args

        port = Ports.get()
        print(f"slot: {port}", flush=True)
        fc_args["client_port"] = port
        env = gymnasium.make("civrealm/FreecivBase-v0")
        obs, info = env.reset(client_port=port)

        strats = {s.name: s for s in ALL_STRATEGIES}
        want = next((n for n in strats if args.strategy in n.lower()), None)
        strategy = strats.get(want, DEFENSIVE)
        gen = ActionOptionGenerator()
        heuristic_gen = HeuristicGenerator(strategy=strategy)
        core = DOFCalculusCore(lookahead_horizon=3, context_switch_penalty=0.5)
        ex = GameStateExtractor(my_player_id=0)
        print(f"strategy: {getattr(strategy, 'name', strategy)}")

        for _step_idx in range(args.turns):
            for _ in range(args.per_turn):
                turn = info.get("turn", 1)
                state = describe(ex, obs, info, turn)
                obs, info = decide(env, gen, heuristic_gen, core, state,
                                   info.get("available_actions") or {}, obs, info)
                if info.get("turn", turn) != turn:
                    break  # ход сменился — дальше закрывать нечего
            obs, _r, term, trunc, info = env.step(None)
            if term or trunc:
                print("(игра окончена)")
                break
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    import traceback

    try:
        main()
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        print(f"ERR: {type(exc).__name__}: {exc}")
        raise SystemExit(3)
