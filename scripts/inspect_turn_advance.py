#!/usr/bin/env python3
"""Does the game ever advance past turn 1? Are AI opponents actually acting?

Checks three things on a live game:
  1. is there an end-turn action in the action space, and under which controller;
  2. does `info['turn']` advance when we keep acting (i.e. do the other
     civilisations ever get their turn);
  3. what the observation says about the game/client state (phase, turn).

Usage: .venv/bin/python scripts/inspect_turn_advance.py
"""
from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
sys.argv = ["x"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gymnasium
from civrealm.configs import fc_args
from civrealm.freeciv.utils.port_utils import Ports


def main() -> int:
    port = Ports.get()
    print(f"slot: {port}")
    fc_args["client_port"] = port

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=port)

    # 1. hunt for end-turn style actions
    print("\naction names mentioning turn/done/end:")
    found = []
    for ctrl_type, actors in (info.get("available_actions") or {}).items():
        for actor_id, actions in actors.items():
            for name, params in actions.items():
                if any(tok in name.lower() for tok in ("turn", "done", "end")):
                    found.append((ctrl_type, actor_id, name, bool(params)))
    for ctrl_type, actor_id, name, valid in found:
        print(f"   {ctrl_type}/{actor_id}: {name!r} valid={valid}")
    if not found:
        print("   (none)")

    print("\nclient/game state keys:")
    for key in ("client", "game"):
        value = obs.get(key)
        if isinstance(value, dict):
            for k, v in list(value.items())[:15]:
                print(f"   {key}.{k} = {str(v)[:60]}")

    # 2. does the turn advance while we act?
    ttl = info.get("turn")
    print(f"\nstarting turn = {ttl}")
    for i in range(40):
        avail = info.get("available_actions") or {}
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
            print(f"   step {i}: no valid action -> cannot advance")
            break
        obs, _r, term, trunc, info = env.step(action)
        if info.get("turn") != ttl or term or trunc:
            print(f"   step {i}: turn {ttl} -> {info.get('turn')} "
                  f"(terminated={term} truncated={trunc}) after {action}")
            ttl = info.get("turn")
        if term or trunc:
            break
    print(f"final turn = {info.get('turn')} after 40 steps")

    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())