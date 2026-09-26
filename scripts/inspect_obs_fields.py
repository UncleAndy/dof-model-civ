#!/usr/bin/env python3
"""What does the observation actually contain for units and cities?

Enumerates the real fields available to the bridge (from saved fixtures) so the
DoF calibration can be based on facts rather than on the handful of fields the
extractor happens to read today.

Usage: .venv/bin/python scripts/inspect_obs_fields.py
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict

sys.argv = ["x"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.json")))


def snapshots(blob):
    """Fixtures are either a snapshot, a list of snapshots, or a stack of them."""
    if isinstance(blob, list):
        return blob
    if isinstance(blob, dict) and "observation" in blob:
        return [blob]
    return []


def main() -> int:
    print(f"fixtures found: {[os.path.basename(f) for f in FIXTURES]}\n")

    unit_keys: Counter = Counter()
    unit_sample: dict = {}
    city_keys: Counter = Counter()
    city_sample: dict = {}
    actions_by_ctrl: defaultdict = defaultdict(Counter)
    unit_types: Counter = Counter()
    n_units: list = []
    n_cities: list = []
    turns: list = []

    for path in FIXTURES:
        try:
            blob = json.load(open(path, encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {os.path.basename(path)}: {exc}")
            continue

        for snap in snapshots(blob):
            obs = snap.get("observation") or {}
            info = snap.get("info") or {}
            units = obs.get("unit") or {}
            cities = obs.get("city") or {}

            n_units.append(len(units))
            n_cities.append(len(cities))
            turns.append(info.get("turn"))

            for u in units.values():
                if isinstance(u, dict):
                    unit_keys.update(u.keys())
                    unit_types[u.get("type_rule_name")] += 1
                    if len(unit_sample) < 3:
                        unit_sample[f"unit_{len(unit_sample)}"] = u
            for c in cities.values():
                if isinstance(c, dict):
                    city_keys.update(c.keys())
                    if len(city_sample) < 3:
                        city_sample[f"city_{len(city_sample)}"] = c

            for ctrl, actors in (info.get("available_actions") or {}).items():
                if not isinstance(actors, dict):
                    continue
                for actor_id, actions in actors.items():
                    if isinstance(actions, dict):
                        valid = sum(1 for p in actions.values() if p)
                    elif isinstance(actions, (list, tuple)):
                        valid = len(actions)
                    else:
                        continue
                    if valid:
                        actions_by_ctrl[ctrl][f"actor {actor_id}"] = valid

    print(f"snapshots: {len(turns)}  turns: {turns[:12]}")
    print(f"units per snapshot: {n_units[:12]}   cities per snapshot: {n_cities[:12]}")
    print(f"unit types seen: {dict(unit_types)}\n")

    print("=== UNIT fields present in real observations ===")
    for key, count in unit_keys.most_common():
        print(f"  {key:<28} seen in {count} units")
    print("\n  sample units:")
    for name, unit in unit_sample.items():
        print(f"    {name}: {json.dumps(unit, ensure_ascii=False)[:400]}")

    print("\n=== CITY fields present in real observations ===")
    if city_keys:
        for key, count in city_keys.most_common():
            print(f"  {key:<28} seen in {count} cities")
        print("\n  sample cities:")
        for name, city in city_sample.items():
            print(f"    {name}: {json.dumps(city, ensure_ascii=False)[:600]}")
    else:
        print("  (no cities in any saved snapshot — a city-bearing capture is needed)")

    print("\n=== valid actions available per controller (real snapshots) ===")
    for ctrl, actors in actions_by_ctrl.items():
        print(f"  {ctrl}: {dict(actors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())