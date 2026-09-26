#!/usr/bin/env python3
"""Realism check: what unit types/health does a real start state contain, and
what DoF does the population-aware model assign them?

Runs entirely on the saved fixture — no live stand needed.

Usage: .venv/bin/python scripts/inspect_unit_realism.py
"""
from __future__ import annotations

import json
import os
import sys

sys.argv = ["x"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from env.config import DOF_SCALE, POPULATION_UNIT_TYPES  # noqa: E402
from env.entity_extractor import GameStateExtractor  # noqa: E402


def main() -> int:
    fixture = os.path.join(ROOT, "tests", "fixtures", "real_obs_01.json")
    blob = json.load(open(fixture, encoding="utf-8"))
    # The fixture is a list of captured snapshots (observation/info/turn triples).
    if isinstance(blob, list):
        snap = blob[0]
        info = snap.get("info", {})
        obs = snap.get("observation", snap)
    else:
        info = blob.get("info", {})
        obs = blob.get("observation", blob)

    units = obs.get("unit", {})
    print(f"units in the start state ({len(units)}):")
    for uid, unit in units.items():
        print(f"  unit {uid}: type={unit.get('type_rule_name')!r} "
              f"health={unit.get('health')} max_moves={unit.get('max_moves')}")

    extractor = GameStateExtractor(my_player_id=0)
    result = extractor.extract(obs, info, info.get("turn", 1))

    print("\nDoF assigned by the model:")
    for entity_id in sorted(result.state.entities):
        if entity_id.startswith("unit_"):
            dof = result.state.entities[entity_id].current_dof
            print(f"  {entity_id:<12} dof={dof:.3f}  options={dof * DOF_SCALE:.2f}")

    types = {(u.get("type_rule_name") or "") for u in units.values()}
    population_types = {t for t in types if t.strip().lower() in POPULATION_UNIT_TYPES}
    print(f"\nunit types seen: {sorted(types)}")
    print(f"recognised as population-carrying: {sorted(population_types)} "
          f"(configured: {sorted(POPULATION_UNIT_TYPES)})")
    if types and not population_types:
        print("WARNING: no unit type in this state is treated as population-carrying; "
              "check POPULATION_UNIT_TYPES against the real ruleset names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())