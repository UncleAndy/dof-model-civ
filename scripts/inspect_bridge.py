#!/usr/bin/env python3
"""Compare the DOF action bridge against a live CivRealm action space.

Opens one game, runs GameStateExtractor + ActionOptionGenerator +
HeuristicGenerator exactly as the DOF agent does, and reports for each
generated candidate whether it can actually be executed:

  * does the ctrl_type exist in available_actions?
  * does the actor id exist?
  * does the action name exist?
  * is the action valid (non-empty params — civrealm's rule)?

Diagnostic only. Usage: .venv/bin/python scripts/inspect_bridge.py
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

_p = argparse.ArgumentParser()
_p.add_argument("--turns", type=int, default=3)
_ARGS, _rest = _p.parse_known_args()
sys.argv = [sys.argv[0]] + _rest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gymnasium
from civrealm.configs import fc_args

from env.entity_extractor import GameStateExtractor
from env.action_mapper import ActionOptionGenerator
from brain.generator.heuristics import ALL_STRATEGIES, HeuristicGenerator


def diagnose(option_id: str, avail: dict) -> str:
    parts = str(option_id).split("_", 2)
    if len(parts) < 3:
        return "unparsable"
    ctrl_type, actor_id, action_name = parts
    if ctrl_type not in avail:
        return f"NO ctrl '{ctrl_type}'"
    actors = avail[ctrl_type]
    if actor_id not in actors:
        return f"NO actor '{actor_id}' in {ctrl_type}"
    actions = actors[actor_id]
    if action_name not in actions:
        return f"NO action '{action_name}' for {ctrl_type}/{actor_id}"
    if not actions[action_name]:
        return "action present but INVALID (empty params)"
    return "OK"


def main() -> int:
    from civrealm.freeciv.utils.port_utils import Ports

    port = Ports.get()
    print(f"slot: {port}")
    fc_args["client_port"] = port

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=port)

    extractor = GameStateExtractor(my_player_id=0)
    mapper = ActionOptionGenerator()

    for i in range(_ARGS.turns):
        avail = info.get("available_actions", {})
        dr = extractor.extract(obs, info, info.get("turn", i))
        state = dr.state

        print(f"\n=== turn {info.get('turn')} | real ctrl types: {sorted(avail)}")
        print(f"    entities: {len(state.entities)}")

        try:
            options = mapper.generate_from_state(state, avail)
        except Exception as exc:  # noqa: BLE001
            print(f"    !! mapper.generate_from_state raised: {type(exc).__name__}: {exc}")
            break

        print(f"    generated options: {len(options)}")
        prefixes: dict[str, int] = {}
        verdicts: dict[str, int] = {}
        for opt in options:
            oid = opt.get("option_id", "")
            prefixes[oid.split("_", 1)[0]] = prefixes.get(oid.split("_", 1)[0], 0) + 1
            v = diagnose(oid, avail)
            key = "OK" if v == "OK" else v.split(" ", 1)[0]
            verdicts[key] = verdicts.get(key, 0) + 1

        print(f"    option prefixes: {prefixes}")
        print(f"    verdicts:        {verdicts}")
        for opt in options[:5]:
            print(f"      {opt.get('option_id')}  ->  {diagnose(opt['option_id'], avail)}")

        gen = HeuristicGenerator(strategy=ALL_STRATEGIES[0])
        try:
            cands = gen.generate_candidates(state, avail)
            best = gen.select_best(cands, state) if cands else None
            print(f"    heuristics picked: {best.get('option_id') if best else None}"
                  f"  ->  {diagnose(best['option_id'], avail) if best else 'n/a'}")
        except Exception as exc:  # noqa: BLE001
            print(f"    !! heuristics raised: {type(exc).__name__}: {exc}")

        # advance with any valid action so the game progresses
        action = None
        for ctrl_type, actors in avail.items():
            for actor_id, actions in actors.items():
                for name, params in actions.items():
                    if params:
                        action = (ctrl_type, actor_id, name)
                        break
                if action:
                    break
            if action:
                break
        if action is None:
            print("    no valid action available; stopping")
            break
        obs, _r, term, trunc, info = env.step(action)
        if term or trunc:
            print("    game ended")
            break

    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())