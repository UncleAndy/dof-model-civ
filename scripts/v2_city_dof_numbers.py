"""Числа DoF города по замерам меню (для согласования с Andy, код не трогаю)."""
from __future__ import annotations

import json
import pathlib
import statistics
from collections import Counter, defaultdict

rows = [json.loads(l) for l in pathlib.Path("knowledge/city_growth.jsonl").read_text().splitlines() if l.strip()]
print(f"записей: {len(rows)}")

tr = [r["переходов_предложено"] for r in rows if isinstance(r.get("переходов_предложено"), int)]
fam = [r["семейств"] for r in rows if isinstance(r.get("семейств"), int)]
pos = [r["позиций_постройки"] for r in rows if isinstance(r.get("позиций_постройки"), int)]
print(f"переходов_предложено: n={len(tr)} медиана {statistics.median(tr)} мин {min(tr)} макс {max(tr)}"
      f" распределение {dict(sorted(Counter(tr).items()))}")
print(f"семейств: медиана {statistics.median(fam)} распределение {dict(sorted(Counter(fam).items()))}")
print(f"позиций_постройки: медиана {statistics.median(pos)} распределение {dict(sorted(Counter(pos).items()))}")

by_size: dict[int, list[int]] = defaultdict(list)
for r in rows:
    if isinstance(r.get("размер"), int) and isinstance(r.get("переходов_предложено"), int):
        by_size[r["размер"]].append(r["переходов_предложено"])
print("\nпо размеру города (переходов_предложено):")
for size in sorted(by_size):
    v = by_size[size]
    print(f"  размер {size}: n={len(v)} медиана {statistics.median(v)} мин {min(v)} макс {max(v)}")

print("\nсемейства (что именно предлагается):")
cf = Counter()
for r in rows:
    for f in r.get("семейства") or []:
        cf[f] += 1
print(" ", dict(cf.most_common(10)))

import math
med = statistics.median(tr)
print(f"\nцена основания города при DoF = медиана({med}) → ln = {math.log(med):.4f}")
print("цена исследования (из трассы, ход 1): +0.097")
print(f"порог победы: ln(DoF_city) > 0.097 ⇔ DoF_city > {math.exp(0.097):.4f}")