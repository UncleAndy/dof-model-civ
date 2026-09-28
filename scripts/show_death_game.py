#!/usr/bin/env python
"""Полная запись одного матча из срезов §10.29, ход за ходом.

Печатаю по строке на ход: сущности, свои города (размер/еда/surplus), свои юниты,
знание клиента (города/поселенцы/разбит) и ПОЛНЫЙ текст сообщений мира — чтобы
механизм потери читался по записи, а не по догадке.
"""
import json
import sys

path = sys.argv[1]
wanted = int(sys.argv[2]) if len(sys.argv) > 2 else 5
rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
game = sorted([r for r in rows if r.get("эпизод") == wanted],
              key=lambda r: r.get("turn_played") or 0)
if not game:
    print(f"матч {wanted} не найден; есть матчи:",
          sorted({r.get('эпизод') for r in rows}))
    raise SystemExit(0)
print(f"матч {wanted}: строк {len(game)}  порт {game[0].get('порт')} "
      f"ветвь {game[0].get('ветвь')}")
for r in game:
    ctrl = r.get("controller") or {}
    print("-" * 100)
    print(f"ход {r.get('turn')} (сыграно {r.get('turn_played')})  "
          f"сущ={r.get('obs_entities')}  город_записей={r.get('n_city_recs')} "
          f"юнит_записей={r.get('n_unit_recs')}")
    print(f"  свои города (x,y,размер,склад,surplus,недовольные,prod): "
          f"{[(c.get('x'), c.get('y'), c.get('size'), c.get('food_stock'), c.get('surplus_food'), c.get('ppl_unhappy'), c.get('production_value')) for c in r.get('my_cities') or []]}")
    print(f"  свои юниты (тип,x,y,ходов): "
          f"{[(u.get('type'), u.get('x'), u.get('y'), u.get('moves')) for u in r.get('my_units') or []]}")
    print(f"  чужие юниты (владелец,тип,x,y): "
          f"{[(u.get('owner'), u.get('type'), u.get('x'), u.get('y')) for u in r.get('foreign_units') or []]}")
    print(f"  чужие города (владелец,x,y,размер): "
          f"{[(c.get('owner'), c.get('x'), c.get('y'), c.get('size')) for c in r.get('foreign_cities') or []]}")
    print(f"  клиент: городов={ctrl.get('городов_контроллер')} "
          f"юнитов={ctrl.get('юнитов_контроллер')} "
          f"поселенцы={ctrl.get('есть_поселенцы')} разбит={ctrl.get('разбит')} "
          f"состояние={ctrl.get('состояние_клиента')}")
    print(f"  предложено: {r.get('offered')}")
    print(f"  жив={r.get('is_alive')} счёт={r.get('score')} золото={r.get('gold')}")
    print(f"  СООБЩЕНИЯ: {r.get('messages')!r}")