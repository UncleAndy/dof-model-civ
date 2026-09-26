#!/usr/bin/env python3
"""What can a city produce, and what does the observation say about it?

Reads a saved real snapshot and prints: which controllers expose actions, the
city's producible-unit mask, its current project, and its built improvements.

Usage: .venv/bin/python scripts/inspect_city_production.py
"""
from __future__ import annotations

import json
import os
import sys

sys.argv = ["x"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    blob = json.load(open(os.path.join(ROOT, "tests", "fixtures",
                                       "real_obs_01.json"), encoding="utf-8"))
    for snap in (blob if isinstance(blob, list) else [blob]):
        info = snap.get("info") or {}
        obs = snap.get("observation") or {}
        if not (obs.get("city") or {}):
            continue

        print("== controllers exposed in available_actions ==")
        for ctrl, actors in (info.get("available_actions") or {}).items():
            if isinstance(actors, dict):
                detail = ", ".join(
                    f"{a}:{len(v) if isinstance(v, (dict, list)) else '?'}"
                    for a, v in list(actors.items())[:6])
            else:
                detail = f"({type(actors).__name__}, {len(actors)})"
            print(f"  {ctrl:<8} {detail}")

        for cid, city in (obs.get("city") or {}).items():
            print(f"\n== city {cid} ({city.get('name')}) ==")
            print(f"  size={city.get('size')} state={city.get('state')} "
                  f"prod_kind={city.get('production_kind')} "
                  f"prod_value={city.get('production_value')} "
                  f"turns_to_complete={city.get('turns_to_prod_complete')}")
            for key in ("can_build_unit", "improvements"):
                mask = city.get(key)
                if isinstance(mask, list):
                    true_idx = [i for i, v in enumerate(mask) if v]
                    print(f"  {key}: {len(mask)} entries, true at {true_idx}")
                else:
                    print(f"  {key}: {mask!r}")

        print("\n== city controller actions (if any) ==")
        city_actions = (info.get("available_actions") or {}).get("city")
        if not city_actions:
            print("  (city controller not present in this snapshot)")
        else:
            for actor, entry in list(city_actions.items())[:3]:
                names = entry.keys() if isinstance(entry, dict) else entry
                print(f"  actor {actor}: {list(names)[:25]}")
        return 0

    print("no snapshot with a city found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())