"""Отчёт по ЗАЩИТЕ: измерима ли уже цена ответа на угрозу.

Сравнивает исходы боёв, начатых врагом, по признаку «наш юнит был укреплён». Пока записей мало,
честный ответ — «не измеримо»: цена защитника не выдумывается (порог MIN_FIGHTS = 5 на плечо).
"""
from __future__ import annotations

import pathlib
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402

MIN_FIGHTS = 5
g = KnowledgeGraph.load(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world.json")
fights = [r for r in (g.observed.get("бой") or []) if isinstance(r, dict)]
enemy = [f for f in fights if f.get("инициатор") == "враг"]
own = [f for f in fights if f.get("инициатор") != "враг"]
print(f"боёв всего: {len(fights)} (начатых врагом {len(enemy)}, наших {len(own)})")

by = defaultdict(list)
for f in enemy:
    by[bool(f.get("наш_укреплён"))].append(f)
for fortified, recs in sorted(by.items()):
    lost = sum(1 for r in recs if r.get("наш_потерян"))
    hurt = sum(1 for r in recs if r.get("наш_ранен"))
    atk = [r.get("чужой_атака") for r in recs if isinstance(r.get("чужой_атака"), (int, float))]
    do = [r.get("наш_до") for r in recs if isinstance(r.get("наш_до"), (int, float))]
    print(f"\nнаш юнит {'УКРЕПЛЁН' if fortified else 'не укреплён'}: n={len(recs)}")
    print(f"  потерян {lost}, ранен {hurt}; доля потерь {lost / len(recs):.2f}")
    if atk:
        print(f"  атака чужого: медиана {statistics.median(atk):.1f} (n={len(atk)})")
    if do:
        print(f"  наша защита: медиана {statistics.median(do):.1f} (n={len(do)})")

n_fort = len(by.get(True, []))
n_plain = len(by.get(False, []))
print(f"\nпорог MIN_FIGHTS={MIN_FIGHTS} на плечо:")
if n_fort >= MIN_FIGHTS and n_plain >= MIN_FIGHTS:
    print("  ДАННЫХ ХВАТАЕТ — цену защитника можно считать замером (сравнение долей потерь).")
else:
    print(f"  НЕ ХВАТАЕТ (укреплён {n_fort}, не укреплён {n_plain}) — цену защитника НЕ считаем; "
          f"нужно набрать боёв, где наш юнит стоит укреплённым под ударом.")