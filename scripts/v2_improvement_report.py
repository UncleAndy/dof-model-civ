"""Отчёт: вклад улучшений (канал `improvement_unlock`) и что накоплено про город.

Печатает ЗАМЕРЫ, а не оценки: сколько улучшений уже измерено, чему равно их влияние на
опубликованное меню города, и сколько записей города накоплено.
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402

g = KnowledgeGraph.load(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world.json")
rows = [r for r in (g.observed.get("city_output") or []) if isinstance(r, dict)]
print(f"записей города (city_output): {len(rows)}")
if rows:
    sizes = Counter(r.get("размер") for r in rows)
    print("по размерам:", dict(sorted(sizes.items(), key=lambda kv: (kv[0] is None, kv[0]))))
    imp = Counter(n for r in rows for n in (r.get("улучшения") or []))
    print(f"улучшений встречалось: {len(imp)}; топ-10: {dict(imp.most_common(10))}")

unl = [r for r in (g.observed.get("improvement_unlock") or []) if isinstance(r, dict)]
print(f"\nизмерено улучшений (improvement_unlock): {len(unl)}")
if unl:
    vals = [r.get("значение") for r in unl if isinstance(r.get("значение"), (int, float))]
    print(f"  медиана вклада: {statistics.median(vals)}; максимум {max(vals)}; ненулевых "
          f"{sum(1 for v in vals if v > 0)} из {len(vals)}")
    for r in sorted(unl, key=lambda x: -float(x.get("значение") or 0))[:10]:
        print(f"  {r.get('улучшение')}: +{r.get('значение')} (n с={r.get('n_с')}, без={r.get('n_без')})")
print("\nвывод: улучшения, у которых вклад 0, новых действий НЕ открывают — их ценность в скорости "
      "(наука/щиты), и её надо мерить отдельно, а не выдавать за меню.")