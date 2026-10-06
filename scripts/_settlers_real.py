"""Проверка §10.116 (пересмотр) на реальных городах базы: цена поселенца с cover и ценой жителя."""
from __future__ import annotations

import sys

sys.path.insert(0, ".")
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402
from brain.v2.horizon import production_gain  # noqa: E402

g = KnowledgeGraph.load(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world_settlers2.json")
own = [c for c in g.by_kind("city") if c.is_own]
print(f"своих городов в базе: {len(own)}")
for c in own:
    cid = c.eid.split(":", 1)[1]
    size = c.attrs.get("size")
    gv, why = production_gain(g, "produce_Settlers", actor=cid)
    print(f"  city:{cid} размер={size}: gain={gv:.3f}")
    print(f"     {why}")