#!/usr/bin/env python
"""Триггер голода: что происходило с едой города и что мы делали в тот же ход.

Печатает по матчам, где город погиб, ход за ходом: размер, prod_food,
surplus_food, выход клетки центра, ВЫБРАННЫЕ действия и сообщения мира. Триггер
читается как «после какого действия prod_food упал ниже food_cost».
"""
import json
import sys
from collections import defaultdict

path = sys.argv[1]
rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
by_game = defaultdict(list)
for r in rows:
    by_game[r.get("эпизод")].append(r)

print(f"файл {path}: строк {len(rows)}, матчей {len(by_game)}")
for idx in sorted(by_game):
    game = sorted(by_game[idx], key=lambda r: r.get("turn_played") or 0)
    died = any(not r.get("obs_entities") for r in game)
    print("=" * 96)
    print(f"матч {idx} порт {game[0].get('порт')} ветвь {game[0].get('ветвь')} "
          f"ходов {len(game)} {'ПОГИБ' if died else 'выжил'}")
    for r in game:
        cities = r.get("my_cities") or []
        c = cities[0] if cities else {}
        cell = c.get("клетка_центра") or {}
        acts = " ".join("/".join(a) for a in (r.get("действия_за_ход") or []))
        print(f"  ход {r.get('turn'):>3} сущ={r.get('obs_entities'):>3} "
              f"город=({c.get('x')},{c.get('y')}) размер={c.get('size')} "
              f"prod_food={c.get('prod_food')} склад={c.get('food_stock')} "
              f"surplus={c.get('surplus_food')} недов={c.get('ppl_unhappy')} "
              f"клетка={cell.get('выход')} террейн={cell.get('террейн')} "
              f"городов_контр={((r.get('controller') or {}).get('городов_контроллер'))} "
              f"поселенцы={((r.get('controller') or {}).get('есть_поселенцы'))}")
        if acts:
            print(f"        действия: {acts}")
        msg = r.get("messages")
        if msg:
            print(f"        сообщения: {msg}")