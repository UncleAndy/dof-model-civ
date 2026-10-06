"""Замер роста городов: еда-прирост по размеру, траектории размеров, наличие Workers.

Читает city_growth_*.jsonl (поля: ход, город, размер, еда_прирост, щиты, семейства...).
"""
from __future__ import annotations

import collections
import json
import statistics
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/city_growth_ab116_A.jsonl"
rows = [json.loads(l) for l in open(path, encoding="utf-8", errors="replace") if l.strip()]
print(f"файл: {path}; строк {len(rows)}")

food = collections.defaultdict(list)
for r in rows:
    if isinstance(r.get("размер"), int) and isinstance(r.get("еда_прирост"), (int, float)):
        food[r["размер"]].append(r["еда_прирост"])
print("\nеда-прирост (медиана) по размеру города:")
for s in sorted(food):
    v = food[s]
    print(f"  размер {s}: медиана {statistics.median(v):+.1f}  "
          f"(мин {min(v):+}, макс {max(v):+}, n={len(v)})")

neg = sum(1 for r in rows if isinstance(r.get("еда_прирост"), (int, float))
          and r["еда_прирост"] < 0)
zero = sum(1 for r in rows if isinstance(r.get("еда_прирост"), (int, float))
           and r["еда_прирост"] == 0)
tot = sum(1 for r in rows if isinstance(r.get("еда_прирост"), (int, float)))
print(f"\nзаписей с еда_прирост: {tot}; из них <0 (голод): {neg}, =0 (стоит): {zero}, "
      f">0 (рост): {tot - neg - zero}")

fam = collections.Counter()
for r in rows:
    for f in (r.get("семейства") or []):
        fam[f] += 1
print("\nсемейства возможностей города:", dict(fam.most_common(12)))