"""Замер под логику «поселенец, когда есть армия и город подрос».

Печатает: паспорт типа Settlers (в т.ч. цена в населении), DoF города по размеру,
и стоимость жителя C_pop = ln(DoF(size)) − ln(DoF(size−1)).
"""
from __future__ import annotations

import json
import math
import statistics
import sys

w = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world_def7.json",
                  encoding="utf-8"))
for e in w["entities"]:
    if isinstance(e, dict) and e.get("eid") in ("unit_type:Settlers", "unit_type:Workers"):
        a = e.get("attrs") or {}
        print(f"{e['eid']}: " + ", ".join(f"{k}={a[k]}" for k in sorted(a)
              if k in ("build_cost", "pop_cost", "dof_families", "attack_strength", "defense_strength")))

print("\nDoF города по размеру (dof_city_reach — «достижимое»):")
import collections
for key in ("dof_city_reach", "dof_city"):
    by = collections.defaultdict(list)
    for r in (w["observed"].get(key) or []):
        if isinstance(r, dict) and "размер" in r:
            by[r["размер"]].append(r["значение"])
    if by:
        print(f"  [{key}]", {s: statistics.median(v) for s, v in sorted(by.items())})

# C_pop = ln(DoF(size)) - ln(DoF(size-1)) по достижимому
by = collections.defaultdict(list)
for r in (w["observed"].get("dof_city_reach") or []):
    if isinstance(r, dict) and "размер" in r:
        by[r["размер"]].append(r["значение"])
med = {s: statistics.median(v) for s, v in by.items()}
print("\nСтоимость жителя C_pop = ln(DoF(size)) − ln(DoF(size−1)):")
for s in sorted(med):
    if s - 1 in med and med[s] > 0 and med[s - 1] > 0:
        print(f"  размер {s}→{s-1}: {math.log(med[s]) - math.log(med[s-1]):.3f}")