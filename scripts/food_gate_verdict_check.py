#!/usr/bin/env python
"""Проверка протечек по ВЕРДИКТУ, который едет вместе с ушедшим действием.

Каждая запись действия в срезах несёт четвёртым полем вердикт Правила F на момент
решения («разрешено: surplus=… проверено правилом F» либо пусто). Протечка — ушедшее
действие семейства БЕЗ вердикта (правило его не смотрело), а не «сверка по началу хода».
"""
import json
import sys
from collections import defaultdict

for path in sys.argv[1:]:
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    fam = defaultdict(int)
    without_verdict = []
    with_verdict = 0
    for r in rows:
        for a in r.get("действия_за_ход") or []:
            name = str(a[2]) if len(a) > 2 else ""
            if not (name.startswith("city_unwork_")
                    or name.startswith("city_change_specialist")
                    or name == "join_city"):
                continue
            key = "city_unwork" if name.startswith("city_unwork") else (
                "city_change_specialist" if name.startswith("city_change") else "join_city")
            fam[key] += 1
            verdict = str(a[3]) if len(a) > 3 else ""
            if verdict:
                with_verdict += 1
            else:
                without_verdict.append((r.get("эпизод"), r.get("turn"), a[:3]))
    print(f"{path}")
    print(f"   ушло действий трёх семейств: {sum(fam.values())} ({dict(fam)})")
    print(f"   из них с вердиктом правила: {with_verdict}; "
          f"БЕЗ вердикта: {len(without_verdict)}")
    for item in without_verdict[:10]:
        print("     без вердикта:", item)
    print(f"   вердиктов «запрещено» среди ушедших: "
          f"{sum(1 for r in rows for a in (r.get('действия_за_ход') or []) if len(a) > 3 and str(a[3]).startswith('запрещ'))}")