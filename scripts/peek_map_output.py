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
    print("  out[43][25] =", json.dumps(out[43][25]) if len(out) > 43 else "-")
terr = mp.get("terrain")
if isinstance(terr, list) and terr:
    print("terrain: строк", len(terr), "в строке", len(terr[0]))
    print("  terrain[43][25] =", terr[43][25])
    print("  ряд y=43:", terr[43][20:30])
city = o.get("city") or {}
for cid, rec in city.items():
    x, y = rec.get("x"), rec.get("y")
    print(f"город {cid} в ({x},{y}): сырой выход клетки центра = {out[y][x]}")
    break
unit = o.get("unit") or {}
for uid, rec in list(unit.items())[:2]:
    x, y = rec.get("x"), rec.get("y")
    print(f"юнит {uid} ({rec.get('type_rule_name')}) в ({x},{y}): "
          f"выход клетки = {out[y][x]}  террейн = {terr[y][x]}")
player = o.get("player") or {}
print("свой игрок:", json.dumps(list(player.values())[0], ensure_ascii=False)[:300])