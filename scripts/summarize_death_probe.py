#!/usr/bin/env python
"""Сводка потерь по срезам §10.29: сколько матчей кончилось «пустым» наблюдением.

Печатает по каждому матчу: сколько ходов дошло, был ли пустой ход, и ЧТО сказал мир
в сообщениях перед потерей (механизм ищется по записи, а не по догадке).
"""
import json
import sys
from collections import defaultdict

for path in sys.argv[1:]:
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    by_game = defaultdict(list)
    for r in rows:
        by_game[r.get("эпизод")].append(r)
    died = []
    for idx in sorted(by_game):
        game = sorted(by_game[idx], key=lambda r: r.get("turn_played") or 0)
        empties = [r for r in game if not r.get("obs_entities")]
        last_ok = None
        for r in game:
            if r.get("obs_entities"):
                last_ok = r
        if empties:
            died.append((idx, game, empties, last_ok))
    print("=" * 96)
    print(f"{path}: матчей {len(by_game)}, из них кончились пустым наблюдением: "
          f"{len(died)}")
    for idx, game, empties, last_ok in died:
        print(f"  матч {idx}: ходов {len(game)}  пусто на ходу "
              f"{empties[0].get('turn')}  порт {game[0].get('порт')}")
        if last_ok is not None:
            print(f"    перед потерей (ход {last_ok.get('turn')}): "
                  f"своих городов {len(last_ok.get('my_cities') or [])}, "
                  f"юнитов {[(u.get('type'), u.get('x'), u.get('y')) for u in last_ok.get('my_units') or []]}")
            print(f"      действия того хода: {last_ok.get('действия_за_ход')}")
            print(f"      сообщения: {str(last_ok.get('messages'))[-220:]!r}")
        e = empties[0]
        ctrl = e.get("controller") or {}
        print(f"    в момент поражения: сущ={e.get('obs_entities')} "
              f"клиент: городов={ctrl.get('городов_контроллер')} "
              f"юнитов={ctrl.get('юнитов_контроллер')} "
              f"поселенцы={ctrl.get('есть_поселенцы')} разбит={ctrl.get('разбит')}")
    # сколько матчей дошло до последнего хода без потерь
    surv = len(by_game) - len(died)
    print(f"  выжило (дошли до конца срезов): {surv}")