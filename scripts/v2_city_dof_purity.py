"""Проверка чистоты замера DoF города: распределение по размеру 1 и связь с окном.

§10.69: число ПРЕДЛОЖЕННЫХ переходов зависит от окна обёртки `PersistentCityProduction`
(наблюдалось «+20 переходов» просто от открывшегося окна). Значит перед заведением числа в граф
надо посмотреть, где окно успело загрязнить замер, а где нет.
"""
from __future__ import annotations

import json
import pathlib
import statistics
from collections import Counter

rows = [json.loads(l) for l in pathlib.Path("knowledge/city_growth.jsonl").read_text().splitlines() if l.strip()]
s1 = [r for r in rows if r.get("размер") == 1]
print(f"записей размера 1: {len(s1)}")
print("распределение переходов (размер 1):", dict(sorted(Counter(r["переходов_предложено"] for r in s1).items())))
print("распределение позиций постройки (размер 1):",
      dict(sorted(Counter(r.get("позиций_постройки") for r in s1).items())))
print("семейств (размер 1):", dict(sorted(Counter(r.get("семейств") for r in s1).items())))

nz = [r["переходов_предложено"] for r in s1 if r["переходов_предложено"] > 0]
print(f"\nбез нулей: n={len(nz)} медиана {statistics.median(nz)} мин {min(nz)} макс {max(nz)}")
print("распределение без нулей:", dict(sorted(Counter(nz).items())))

# связь «переходы ↔ позиции постройки»: если окно добавляет переходы, позиции не растут
print("\nпереходы × позиции_постройки (размер 1):")
pairs = Counter((r["переходов_предложено"], r.get("позиций_постройки")) for r in s1)
for (tr, pos), n in sorted(pairs.items()):
    print(f"  переходов {tr} при позициях {pos}: {n}")

# записи с 0 переходов — какое у них число позиций
z = [r.get("позиций_постройки") for r in s1 if r["переходов_предложено"] == 0]
print(f"\nзаписи с 0 переходов: {len(z)}, позиции постройки: {dict(sorted(Counter(z).items()))}")

# все размеры: доля записей с подозрением на окно (>= 20)
allv = [r["переходов_предложено"] for r in rows]
print(f"\nвсе размеры: записей {len(allv)}, из них >= 20 переходов: {sum(1 for v in allv if v >= 20)}"
      f" ({100 * sum(1 for v in allv if v >= 20) / len(allv):.1f} %)")