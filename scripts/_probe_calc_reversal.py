"""Проба §13.81: выпадает и возвращается ли сущность из состава набора счёта.

Стенд не занимается: читаются записи прошедших сессий. Печатаются числа и примеры имён.
Один проход: имя, выпавшее из набора и появившееся в нём снова, считается вернувшимся.
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
KN = ROOT / "knowledge"

files = sorted(KN.glob("live_trace_*.jsonl"), key=lambda p: p.stat().st_mtime)
print(f"записей: {len(files)}")

all_drop: set[str] = set()
all_back: set[str] = set()
all_new: set[str] = set()
per_file = []

for path in files:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(rows) < 2:
        continue
    sets = [{x.get("id") for x in (r.get("разбивка") or []) if x.get("id")} for r in rows]
    if max(len(s) for s in sets) == 0:
        continue
    seen: set[str] = set()
    drop: set[str] = set()
    back: set[str] = set()
    new: set[str] = set()
    for cur in sets:
        new |= cur - seen
        drop |= (seen - cur)
        back |= (cur & drop)
        seen |= cur
    all_drop |= drop
    all_back |= back
    all_new |= new
    per_file.append((path.name, len(rows), min(len(s) for s in sets), max(len(s) for s in sets),
                     len(drop), len(back), len(new)))

print("\n── по записям ──")
for name, turns, lo, hi, d, b, n in per_file:
    print(f"  {name}: ходов {turns}, в наборе {lo}..{hi}, выпало {d}, вернулось {b}, новых {n}")

print("\n── итог по всем записям ──")
print(f"  выпадало имён: {len(all_drop)}")
print(f"  вернулось имён: {len(all_back)}")
print(f"  новых имён: {len(all_new)}")
if all_back:
    print(f"  примеры вернувшихся: {sorted(all_back)[:8]}")
    print("  вердикт по объявленному правилу: односторонность ОПРОВЕРГНУТА на этих данных")
else:
    print("  вердикт по объявленному правилу: возвращений НЕ наблюдалось — односторонность")
    print("  не опровергнута (и это не то же самое, что «невозможно»)")
