"""Проверка компонент §10.116: цена жителя C_pop и cover (риск/индекс)."""
from __future__ import annotations

import math
import sys

sys.path.insert(0, ".")
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402
from brain.v2 import threat  # noqa: E402
from brain.v2.calculus import dof_of, index  # noqa: E402

g = KnowledgeGraph.load("knowledge/world_def7.json")
med = {s: g.observed_median("dof_city", {"размер": s}) for s in (1, 2, 3, 4, 5)}
print("DoF города по размеру (dof_city):", med)
print("\nC_pop = ln(DoF(s)) − ln(DoF(s−2)) (Settlers стоят 2 жителя):")
for s in (3, 4, 5):
    a, b = med.get(s), med.get(s - 2)
    if a and b and a > 0 and b > 0:
        print(f"  размер {s}→{s-2}: ln({a:g}/{b:g}) = {math.log(a) - math.log(b):.3f}")

risk, det = threat.risk_price(g, dof_of, threat.STRIKE_TURNS)
idx = (index(g) or {}).get("value") or 0.0
cover = max(0.0, 1.0 - (risk / idx)) if idx > 0 else 1.0
print(f"\nриск под ударом = {risk:.3f}; индекс = {idx:.3f}; cover = {cover:.3f}")