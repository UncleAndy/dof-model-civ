#!/usr/bin/env python3
"""What can the starting units do, and what values does the starting city carry?

Real-data counterpart to the calibration discussion: per-unit-type action lists
and a full city dump.

Usage: .venv/bin/python scripts/inspect_start_state.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.argv = ["x"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def snapshots(blob):
    if isinstance(blob, list):
        return blob
    if isinstance(blob, dict) and "observation" in blob:
        return [blob]
    return []


def main() -> int:
    obs_path = os.path.join(ROOT, "tests", "fixtures", "real_obs_01.json")
    for snap in snapshots(json.load(open(obs_path, encoding="utf-8"))):
        info = snap.get("info") or {}
        obs = snap.get("observation") or {}
        units = obs.get("unit") or {}
        if not units:
            continue

        print(f"turn={info.get('turn')} units={len(units)} "
              f"cities={len(obs.get('city') or {})}")

        by_type = defaultdict(list)
        for uid, u in units.items():
            by_type[u.get("type_rule_name")].append(uid)

        actions = (info.get("available_actions") or {}).get("unit") or {}
        for utype, ids in by_type.items():
            print(f"\n=== {utype} (units {ids}) ===")
            sample = units[ids[0]]
            print("  properties: " + ", ".join(
                f"{k}={sample.get(k)}" for k in sorted(sample)))
            offered = set()
            for uid in ids:
                entry = actions.get(uid) or actions.get(str(uid)) or {}
                if isinstance(entry, dict):
                    for name, params in entry.items():
                        if params:
                            offered.add(name)
                elif isinstance(entry, (list, tuple)):
                    for item in entry:
                        if isinstance(item, str):
                            offered.add(item)
            print(f"  valid actions ({len(offered)}): {sorted(offered)[:40]}")

        cities = obs.get("city") or {}
        for cid, city in list(cities.items())[:2]:
            print(f"\n=== city {cid}: {city.get('name')!r} ===")
            for key in sorted(city):
                value = city[key]
                if isinstance(value, (list, dict)):
                    print(f"  {key:<26} {json.dumps(value, ensure_ascii=False)[:200]}")
                else:
                    print(f"  {key:<26} {value}")
        return 0

    print("no snapshot with units found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())