"""Что записано в графе про эффект семейства found_city (откуда −59.2) и как считается проекция."""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402
from brain.v2 import projection as proj_mod  # noqa: E402
from brain.v2.calculus import impute, dof_of  # noqa: E402

g = KnowledgeGraph.load(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world_dof.json")
print("семейства эффектов:")
for k, v in sorted(g.effects.items()):
    cc = v.get("change_counts") or {}
    keys = [a for a in cc if "found" in a or "city" in a]
    print(f"  {k}: seen={v.get('seen')}; ключи_города={keys[:6]}")

for ctrl in ("unit", "city"):
    for fam in ("found_city", "settle", "found"):
        p = proj_mod.project(g, ctrl, fam)
        if p.known or p.new_entities or p.lost_entities or p.changes:
            print(f"\nпроекция {ctrl}/{fam}: known={p.known}; source={p.source}")
            print(f"  new={p.new_entities}; lost={p.lost_entities}; changes={p.changes}")
            for kind, n in (p.new_entities or {}).items():
                print(f"    выигрыш {kind}×{n}: impute={impute(g, kind)} → +{n * __import__('math').log(impute(g, kind)[0]) if impute(g, kind)[0] else None}")
            for kind, n in (p.lost_entities or {}).items():
                v = impute(g, kind)[0]
                print(f"    потеря {kind}×{n}: impute={v}")

own = [e for e in g.by_kind("unit") if e.is_own]
print(f"\nсвоих юнитов в графе: {len(own)}")
for e in own[:4]:
    d, why = dof_of(g, e)
    print(f"  {e.eid} ({e.name}): dof={d} ({why})")
print("impute('unit') =", impute(g, "unit"))