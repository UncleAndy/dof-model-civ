"""Проверка цены города: impute('city') и из чего она сложилась."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from brain.v2.calculus import impute  # noqa: E402
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402

g = KnowledgeGraph.load(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world_dof.json")
print("каналы:")
for k in ("dof_city_reach", "city_own_families", "city_size_buildable", "dof_city"):
    vals = g.observed.get(k) or []
    print(f"  {k}: {len(vals)}; медиана размер1 = {g.observed_median(k, {'размер': 1})}")
types = [float(t.attrs.get("dof_families") or 0) for t in g.by_kind("unit_type")]
types = [v for v in types if v > 0]
print(f"типов юнитов с семейным DoF: {len(types)}; среднее = {sum(types) / len(types):.3f}")
print("impute('city') =", impute(g, "city"))
own = g.observed_median("city_own_families", {"размер": 1})
nb = g.observed_median("city_size_buildable", {"размер": 1})
print(f"расчёт В1: свои семейства {own} + постройки {nb} × среднее {sum(types) / len(types):.3f} "
      f"= {own + nb * sum(types) / len(types):.3f}")
import math
print(f"цена основания: ln({own + nb * sum(types) / len(types):.3f}) = "
      f"{math.log(own + nb * sum(types) / len(types)):.4f}")