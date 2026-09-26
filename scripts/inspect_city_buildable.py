#!/usr/bin/env python3
"""Which production options are actually available right now?

`produce_<Name>` actions form the catalogue of everything a city could make;
an entry is currently available when its params are truthy.

Usage: .venv/bin/python scripts/inspect_city_buildable.py
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.argv = ["x"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def snapshots(blob):
    return blob if isinstance(blob, list) else [blob]


def main() -> int:
    results = []
    for path in ("real_obs_01.json", "real_available_actions.json"):
        full = os.path.join(ROOT, "tests", "fixtures", path)
        if not os.path.exists(full):
            continue
        for snap in snapshots(json.load(open(full, encoding="utf-8"))):
            info = snap.get("info") or {}
            obs = snap.get("observation") or {}
            cities = (info.get("available_actions") or {}).get("city")
            if not cities or not (obs.get("city") or {}):
                continue

            total, available = [], []
            for actor, entry in cities.items():
                items = (entry.items() if isinstance(entry, dict)
                         else [(n, None) for n in entry])
                for name, params in items:
                    if not name.startswith("produce_"):
                        continue
                    total.append(name)
                    if params:                     # truthy = offered now
                        available.append((name, params))

            cid, city = next(iter((obs.get("city") or {}).items()))
            print(f"[{path}] city {cid} ({city.get('name')}), "
                  f"size={city.get('size')}, state={city.get('state')}")
            print(f"  catalogue: {len(set(total))} producible names")
            print(f"  available now: {len(available)}")
            for name, params in available[:12]:
                print(f"    {name} -> {json.dumps(params, ensure_ascii=False)[:160]}")

            mask = city.get("can_build_unit")
            if isinstance(mask, list):
                print(f"  can_build_unit mask: true at "
                      f"{[i for i, v in enumerate(mask) if v]} of {len(mask)}")
            print()
            results.append(path)
    if not results:
        print("no city-bearing snapshot with available_actions found")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())