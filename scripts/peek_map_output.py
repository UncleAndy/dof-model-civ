#!/usr/bin/env python
"""Структура map: как достать выход (еда/щиты/торговля) клетки по (x, y).

Нужна для проверки K3: «город погиб от голода потому, что основан на бедной еде
клетке». Значит, надо уметь читать выход клетки, а не помнить его форму.
"""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/real_obs_01.json"
o = json.load(open(path))
if isinstance(o, list):
    o = o[0]
if "observation" in o and isinstance(o["observation"], dict):
    o = o["observation"]
mp = o.get("map") or {}
print("разделы map:", sorted(mp.keys()))
out = mp.get("output")
print("output: тип", type(out).__name__,
      "длина", len(out) if hasattr(out, "__len__") else "-")
if isinstance(out, list) and out:
    print("  len(out[0]) =", len(out[0]) if hasattr(out[0], "__len__") else "-")
    print("  out[25][43] (наш город) =", json.dumps(out[25][43]) if len(out) > 25 else "-")
terr = mp.get("terrain")
if isinstance(terr, list) and terr:
    print("terrain: строк", len(terr), "в строке", len(terr[0]))
    print("  terrain[25][43] (наш город) =", terr[25][43])
    print("  столбец x=25, y=40..50:", [terr[25][j] for j in range(40, 51)])
city = o.get("city") or {}
for cid, rec in city.items():
    x, y = rec.get("x"), rec.get("y")
    # Порядок слоёв измерен: [x][y] (§13.99).
    print(f"город {cid} в ({x},{y}): сырой выход клетки центра = {out[x][y]}")
    break
unit = o.get("unit") or {}
for uid, rec in list(unit.items())[:2]:
    x, y = rec.get("x"), rec.get("y")
    print(f"юнит {uid} ({rec.get('type_rule_name')}) в ({x},{y}): "
          f"выход клетки = {out[x][y]}  террейн = {terr[x][y]}")
player = o.get("player") or {}
print("свой игрок:", json.dumps(list(player.values())[0], ensure_ascii=False)[:300])