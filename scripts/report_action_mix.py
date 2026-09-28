#!/usr/bin/env python
"""Что агент делает за 30 ходов: семьи действий, движения, города, стек юнитов.

Читается из срезов `--dump-state`: каждое выбранное за ход действие с вердиктом. Вопрос,
который здесь решается числом, а не мнением: расширяется ли агент и ходит ли он вообще —
или стоит в городе и только производит.
"""
import json
import sys
from collections import Counter, defaultdict

path = sys.argv[1]
rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
by_game = defaultdict(list)
for r in rows:
    by_game[r.get("эпизод")].append(r)

total = Counter()
for idx in sorted(by_game):
    game = sorted(by_game[idx], key=lambda r: r.get("turn_played") or 0)
    fam = Counter()
    moves = 0
    cities_founded = 0
    for r in game:
        for a in r.get("действия_за_ход") or []:
            name = str(a[2]) if len(a) > 2 else ""
            if name.startswith("goto") or name in ("move", "road", "irrigate",
                                                   "mine", "fortify", "plant"):
                moves += 1
                fam["движение/работы"] += 1
            elif name.startswith("produce_"):
                fam["производство"] += 1
            elif name == "city_buy_production":
                fam["покупка"] += 1
            elif name == "build_city":
                cities_founded += 1
                fam["основание города"] += 1
            elif name.startswith("research"):
                fam["наука"] += 1
            elif name.startswith("city_"):
                fam["прочее по городу"] += 1
            else:
                fam[f"прочее:{name.split('_')[0]}"] += 1
        total.update(Counter())   # накопление — по матчу, а не по ходу (иначе двойной счёт)
    total.update(fam)     # один раз на матч
    last = game[-1]
    my_units = len(last.get("my_units") or [])
    my_cities = len(last.get("my_cities") or [])
    tiles = Counter((u.get("x"), u.get("y")) for u in (last.get("my_units") or []))
    sett = sum(1 for u in (last.get("my_units") or []) if u.get("type") == "Settlers")
    print(f"матч {idx}: ходов {len(game)}  городов {my_cities}  основано {cities_founded}  "
          f"юнитов {my_units} (поселенцев {sett})")
    print(f"   семьи: {dict(fam)}")
    print(f"   где юниты: {[(pos, n) for pos, n in tiles.most_common(3)]}")
print("=" * 96)
print("ИТОГ по всем матчам:", dict(total))
print(f"движение/работы всего: {total.get('движение/работы', 0)}; "
      f"основание городов: {total.get('основание города', 0)}; "
      f"производство: {total.get('производство', 0)}; покупка: {total.get('покупка', 0)}; "
      f"наука: {total.get('наука', 0)}")