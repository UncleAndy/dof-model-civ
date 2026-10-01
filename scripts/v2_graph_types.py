"""Какие типы сущностей есть в графе (чтобы точно сказать, есть ли там город)."""
from __future__ import annotations

import json
import pathlib
from collections import Counter

data = json.loads(pathlib.Path("knowledge/world.json").read_text())
ents = data.get("entities") or {}
print("entities:", type(ents).__name__, len(ents))
if isinstance(ents, dict):
    items = list(ents.items())
else:
    items = [(e.get("id"), e) for e in ents]
types = Counter()
for k, v in items:
    t = (v or {}).get("тип") or (v or {}).get("type") or "?"
    types[t] += 1
print("типы:", dict(types.most_common(15)))
print("примеры ключей:", [k for k, _ in items[:8]])
print("пример значения:", json.dumps(items[0][1], ensure_ascii=False)[:300])