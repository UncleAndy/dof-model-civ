"""Замер: растёт ли набор возможностей города вместе с городом (и с технологиями).

Читает knowledge/city_growth.jsonl. Отвечает замером, а не предположением.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else
         Path(__file__).resolve().parents[1] / "knowledge" / "city_growth.jsonl")
rows = [json.loads(line) for line in p.open(encoding="utf-8") if line.strip()]
print(f"замеров: {len(rows)}")

by_size: dict = defaultdict(list)
by_build: dict = defaultdict(list)
for r in rows:
    by_size[r.get("размер")].append(r.get("переходов_предложено"))
    by_build[r.get("позиций_постройки")].append(r.get("переходов_предложено"))

print("\n== размер города -> предложено переходов (мин/медиана/макс, n) ==")
for size in sorted(k for k in by_size if isinstance(k, int)):
    v = sorted(x for x in by_size[size] if isinstance(x, int))
    if v:
        print(f"  размер {size}: {v[0]}/{v[len(v)//2]}/{v[-1]}  (n={len(v)})")

print("\n== позиций постройки -> предложено переходов ==")
for b in sorted(k for k in by_build if isinstance(k, int)):
    v = sorted(x for x in by_build[b] if isinstance(x, int))
    if v:
        print(f"  постройки {b}: {v[0]}/{v[len(v)//2]}/{v[-1]}  (n={len(v)})")

print("\n== семейства переходов, встречавшиеся у городов ==")
fam = defaultdict(int)
for r in rows:
    for f in r.get("семейства") or []:
        fam[f] += 1
for k, v in sorted(fam.items(), key=lambda kv: -kv[1]):
    print(f"  {k}: {v}")

print("\n== рост города по ходам (по одному городу) ==")
for r in rows[:24]:
    print(f"  ход {r.get('ход')}: {r.get('город')} размер={r.get('размер')} "
          f"переходов={r.get('переходов_предложено')} постройки={r.get('позиций_постройки')} "
          f"еда={r.get('еда_прирост')}")