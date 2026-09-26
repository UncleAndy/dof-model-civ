#!/usr/bin/env python3
"""What can a city do? Full action catalogue of the city controller.

Usage: .venv/bin/python scripts/inspect_city_actions.py
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
        if not (obs.get("city") or {}):
            continue
        cities = (info.get("available_actions") or {}).get("city") or {}
        for actor, entry in cities.items():
            if isinstance(entry, dict):
                items = list(entry.items())
            else:
                items = [(n, None) for n in entry]

            families = Counter()
            for name, _params in items:
                families[re.sub(r"(_-?\d+)+$", "", name)] += 1
            print(f"city actor {actor}: {len(items)} actions, "
                  f"{len(families)} families\n")
            for family, count in sorted(families.items()):
                print(f"  {family:<34} x{count}")

            print("\n  --- sample params (production-related) ---")
            shown = 0
            for name, params in items:
                if isinstance(params, dict) and re.search(
                        r"change_production|buy|specialist|work", name):
                    print(f"  {name} -> {json.dumps(params, ensure_ascii=False)[:200]}")
                    shown += 1
                    if shown >= 6:
                        break
        return 0
    print("no snapshot with a city found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())