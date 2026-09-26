#!/usr/bin/env python3
"""Research/technology side of the observation.

What fields does a tech carry, how many are researchable, and what research
actions does the tech controller offer?

Usage: .venv/bin/python scripts/inspect_tech_options.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

sys.argv = ["x"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    blob = json.load(open(os.path.join(ROOT, "tests", "fixtures",
                                       "real_obs_01.json"), encoding="utf-8"))
    for snap in (blob if isinstance(blob, list) else [blob]):
        info = snap.get("info") or {}
        obs = snap.get("observation") or {}
        techs = obs.get("tech") or {}
        if not techs:
            continue

        print(f"turn={info.get('turn')}  tech entries in obs['tech']: {len(techs)}")
        keys: Counter = Counter()
        for entry in techs.values():
            if isinstance(entry, dict):
                keys.update(entry.keys())
        print("\nfields seen on tech entries:")
        for key, count in keys.most_common():
            print(f"  {key:<28} in {count}")

        for name, entry in list(techs.items())[:3]:
            print(f"\nsample tech {name}:")
            if isinstance(entry, dict):
                for key in sorted(entry):
                    print(f"  {key:<26} {entry[key]}")

        actions = (info.get("available_actions") or {}).get("tech") or {}
        families = Counter()
        valid = 0
        for actor, entry in actions.items():
            items = (entry.items() if isinstance(entry, dict)
                     else [(n, None) for n in entry])
            for name, params in items:
                families[re.sub(r"_(.*)$", "", name)] += 1
                if params:
                    valid += 1
        print(f"\ntech controller: {len(actions)} actor(s), "
              f"{sum(families.values())} action names, {valid} with truthy params")
        for family, count in families.most_common():
            print(f"  {family:<20} x{count}")

        for actor, entry in actions.items():
            items = (entry.items() if isinstance(entry, dict)
                     else [(n, None) for n in entry])
            shown = [n for n, p in items if p][:6]
            print(f"\n  actor {actor}: researchable examples -> {shown}")
        return 0

    print("no snapshot with tech data found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())