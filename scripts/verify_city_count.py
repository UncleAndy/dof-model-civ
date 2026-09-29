#!/usr/bin/env python
"""Независимая проверка: сколько городов у нашего игрока по срезам наблюдений.

Счёт по действиям 'build_city' может врать (наблюдение накапливает действия за прошлые
ходы). Здесь берём сам мир: множество id городов нашего игрока в каждом срезе, и смотрим
максимум за игру.
"""
import glob
import json
import sys
from collections import defaultdict

PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/h150_base.json.state.jsonl"

rows = []
for line in open(PATH, encoding="utf-8"):
    if line.strip():
        rows.append(json.loads(line))

print(f"файл: {PATH}  строк: {len(rows)}")
print("ключи среза:", sorted(rows[0].keys()))

by_game = defaultdict(list)
for r in rows:
    by_game[r.get("эпизод")].append(r)

for idx, game in sorted(by_game.items(), key=lambda kv: (kv[0] is None, kv[0])):
    game.sort(key=lambda r: r.get("turn_played") or 0)
    cities = game[-1].get("мои_города")
    if cities is None:
        cities = game[-1].get("my_cities")
    print(f"  игра {idx}: ходов {len(game)}, поле городов = {cities!r}")