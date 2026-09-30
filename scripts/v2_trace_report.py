"""Разбор протокола решений: почему агент действовал или молчал."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else
         Path(__file__).resolve().parents[1] / "knowledge" / "traces.jsonl")
rows = []
with p.open(encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass

print(f"решений в протоколе: {len(rows)}")
reasons = Counter()
goals = Counter()
empty = 0
for r in rows:
    reasons[r.get("причина", "?")] += 1
    ch = r.get("выбрано")
    if ch:
        goals[f"{ch.get('kind')}/{ch.get('goal')}"] += 1
    else:
        empty += 1

print("\n== причины выбора ==")
for k, v in reasons.most_common():
    print(f"  {v:4d}  {k}")
print("\n== что выбиралось ==")
for k, v in goals.most_common():
    print(f"  {v:4d}  {k}")
print(f"\nпустых решений: {empty}")

print("\n== индекс по ходам (первые 12 и последние 6 записей) ==")
vals = [(r.get("ход"), r.get("индекс"), r.get("кальк_включено")) for r in rows]
for row in vals[:12] + vals[-6:]:
    print("  ход", row[0], "индекс", (round(row[1], 3) if isinstance(row[1], float) else row[1]),
          "сущностей в calc", row[2])

print("\n== пример пустого решения ==")
for r in rows:
    if not r.get("выбрано"):
        print(json.dumps(r, ensure_ascii=False)[:900])
        break