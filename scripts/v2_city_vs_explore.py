"""Диагностика: почему explore перебивает found_city (числа из трассы, без догадок).

Для каждого решения, где в коридоре был кандидат `found_city`, печатаем:
  * что выбрано,
  * лучший NetDelta по `explore` и по `found_city`,
  * причину выбора.

Так видно, на сколько именно проигрывает основание города, а не «почему-то не ставит».
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_record6.jsonl")
rows = []
for line in path.open():
    line = line.strip()
    if not line:
        continue
    rec = json.loads(line)
    cands = rec.get("кандидаты") or []
    def best(goal: str) -> float | None:
        vals = [c.get("net_delta") for c in cands
                if (c.get("эффект") or [None])[0] == goal and c.get("net_delta") is not None]
        return max(vals) if vals else None
    fc = best("found_city")
    if fc is None:
        continue
    rows.append({
        "ход": rec.get("ход"),
        "выбрано": (rec.get("выбрано") or {}).get("goal"),
        "explore": best("explore"),
        "found_city": fc,
        "channel": best("channel"),
        "причина": rec.get("причина"),
    })

print(f"решений с кандидатом found_city: {len(rows)}")
if not rows:
    sys.exit(0)
print(f"выбрано в них: {dict((k, sum(1 for r in rows if r['выбрано'] == k)) for k in {r['выбрано'] for r in rows})}")
fc = [r["found_city"] for r in rows]
ex = [r["explore"] for r in rows if r["explore"] is not None]
print(f"NetDelta found_city: медиана {statistics.median(fc):.4f}, макс {max(fc):.4f}, мин {min(fc):.4f}")
if ex:
    print(f"NetDelta explore (в тех же решениях): медиана {statistics.median(ex):.4f}, макс {max(ex):.4f}")
    diffs = [r["explore"] - r["found_city"] for r in rows if r["explore"] is not None]
    print(f"разность explore − found_city: медиана {statistics.median(diffs):.4f}")
print("первые 5 решений:")
for r in rows[:5]:
    print(f"  ход {r['ход']}: выбрано {r['выбрано']}; explore={r['explore']}; found_city={r['found_city']:.4f}"
          f"; channel={r['channel']}; причина: {r['причина']}")