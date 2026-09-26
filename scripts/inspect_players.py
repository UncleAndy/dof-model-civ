#!/usr/bin/env python3
"""Who else is in the game? Report the players present in a live CivRealm game.

Answers concretely: are there other civilisations (AI players) besides ours, how
many, and do we see their activity. Read-only diagnostic.

Usage: .venv/bin/python scripts/inspect_players.py
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

    print(f"\nobservation keys: {sorted(obs)}")

    # Players visible in the observation
    for key in ("player", "players", "dipl", "diplomacy"):
        value = obs.get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            print(f"\nobs['{key}'] ({len(value)} entries):")
            for pid, pdata in list(value.items())[:10]:
                if isinstance(pdata, dict):
                    name = pdata.get("name") or pdata.get("username") or "?"
                    alive = pdata.get("is_alive", pdata.get("alive", "?"))
                    ai = pdata.get("ai", pdata.get("is_ai", "?"))
                    print(f"   id={pid} name={name!r} alive={alive} ai={ai}")
                else:
                    print(f"   id={pid} -> {str(pdata)[:80]}")
        else:
            print(f"\nobs['{key}'] = {str(value)[:200]}")

    # Who owns the units/cities we can see (owners other than us => others present)
    def owners(key_in_obs: str) -> set:
        found = set()
        for item in (obs.get(key_in_obs) or {}).values():
            if isinstance(item, dict) and "owner" in item:
                found.add(item["owner"])
        return found

    unit_owners = owners("unit")
    city_owners = owners("city")
    print(f"\nunit owners seen: {sorted(unit_owners)}")
    print(f"city owners seen: {sorted(city_owners)}")

    # Diplomacy actors in available actions = other nations we can talk to
    dipl_actors = list((info.get("available_actions", {}).get("dipl") or {}).keys())
    print(f"diplomacy actors in available_actions: {dipl_actors}")

    # Turn / phase and whether the game waits for other players
    print(f"\nturn={info.get('turn')}  our_id={fc_args.get('player_id', '?')}")

    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())