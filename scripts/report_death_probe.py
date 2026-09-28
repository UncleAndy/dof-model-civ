#!/usr/bin/env python
"""Разбор срезов §10.29: где и как сторона теряет город.

Читает JSONL срезов и печатает по каждому матчу: ходы, последнюю НЕПУСТУЮ строку
(город/юниты/видимые чужие) и строку «поражения» (пусто) — с независимым знанием
клиента и сообщениями мира. Вердикт по K1..K5 читается из этих записей.
"""
import json
import sys
from collections import defaultdict

path = sys.argv[1]
rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
by_game = defaultdict(list)
for row in rows:
    by_game[row.get("эпизод")].append(row)

print(f"файл: {path}   строк: {len(rows)}   матчей: {len(by_game)}")
for idx in sorted(by_game):
    game = sorted(by_game[idx], key=lambda r: r.get("turn_played") or 0)
    turns = [r.get("turn") for r in game]
    empties = [r for r in game if not r.get("obs_entities")]
    print("=" * 100)
    print(f"матч {idx}  порт {game[0].get('порт')}  ветвь {game[0].get('ветвь')}  "
          f"ходов в срезах {len(game)}  ходы {turns[0]}..{turns[-1]}  "
          f"пустых наблюдений {len(empties)}")
    last_ok = None
    for r in game:
        if r.get("obs_entities"):
            last_ok = r
    if last_ok is not None:
        cities = [(c.get("x"), c.get("y"), c.get("size"), c.get("food_stock"),
                   c.get("surplus_food"), c.get("ppl_unhappy")) for c in last_ok["my_cities"]]
        units = [(u.get("type"), u.get("x"), u.get("y")) for u in last_ok["my_units"]]
        print(f"  последнее НЕПУСТОЕ наблюдение: ход {last_ok.get('turn')} "
              f"сущ={last_ok['obs_entities']}")
        print(f"    свои города (x,y,размер,склад_еды,surplus,недовольные): {cities}")
        print(f"    свои юниты (тип,x,y): {units}")
        print(f"    видно чужих юнитов: {[(u.get('owner'), u.get('type'), u.get('x'), u.get('y')) for u in last_ok['foreign_units']]}")
        print(f"    чужих городов видно: {[(c.get('owner'), c.get('x'), c.get('y'), c.get('size')) for c in last_ok['foreign_cities']]}")
        print(f"    предложено контроллеров: {last_ok.get('offered')}")
        print(f"    клиент: {last_ok.get('controller')}")
        print(f"    жив={last_ok.get('is_alive')} счёт={last_ok.get('score')}")
        print(f"    сообщения: {str(last_ok.get('messages'))[-300:]!r}")
    for r in empties[:3]:
        print(f"  ПУСТО на ходу {r.get('turn')}: сущ={r['obs_entities']} "
              f"записей города={r['n_city_recs']} юнита={r['n_unit_recs']} "
              f"жив={r.get('is_alive')} счёт={r.get('score')} золото={r.get('gold')}")
        print(f"    предложено: {r.get('offered')}")
        print(f"    КЛИЕНТ (независимо): {r.get('controller')}")
        print(f"    сообщения: {str(r.get('messages'))!r}")
    if not empties:
        tail = game[-1]
        print(f"  пустых нет; последний ход {tail.get('turn')}: "
              f"свои города={[(c.get('x'), c.get('y'), c.get('size')) for c in tail['my_cities']]} "
              f"жив={tail.get('is_alive')} счёт={tail.get('score')} "
              f"сообщения={str(tail.get('messages'))[-160:]!r}")