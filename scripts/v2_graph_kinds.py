"""Типы (kind) сущностей графа и наличие у них измеренного DoF."""
from __future__ import annotations

import json
import pathlib
from collections import Counter

data = json.loads(pathlib.Path("knowledge/world.json").read_text())
ents = data.get("entities") or []
kinds = Counter(e.get("kind") for e in ents)
print("kind:", dict(kinds.most_common(20)))
with_dof = Counter(e.get("kind") for e in ents if e.get("dof") is not None)
print("с непустым dof:", dict(with_dof.most_common(20)))
cities = [e for e in ents if e.get("kind") == "city"]
print(f"городов в графе: {len(cities)}")
for e in cities[:5]:
    print(" ", json.dumps(e, ensure_ascii=False)[:250])