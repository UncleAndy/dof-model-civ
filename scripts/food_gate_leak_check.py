#!/usr/bin/env python
"""Проверка «протечек» Правила F: не ушло ли на сервер действие, которое оно запрещает.

Считается по ЗАПИСЯМ: для каждого выполненного действия трёх семейств берётся состояние
города В ТОТ ХОД (размер, `surplus_food`), цена действия (для `city_unwork` — еда целевой
клетки из окна) и проверяется правило. Любое запрещённое, но выполненное действие —
протечка, и она называется по числам.
"""
import json
import sys
from collections import Counter, defaultdict

MAX_TILE_FOOD = 3.0
FOOD_COST = 2.0


def tile_food(city, name):
    parts = str(name).split("_")
    try:
        off = (int(parts[-2]), int(parts[-1]))
    except (TypeError, ValueError, IndexError):
        return None
    cell = (city.get("окно_клеток") or {}).get(f"{off[0]},{off[1]}")
    vec = (cell or {}).get("xy") if isinstance(cell, dict) else None
    return float(vec[0]) if isinstance(vec, list) and vec else None


for path in sys.argv[1:]:
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    by_game = defaultdict(list)
    for r in rows:
        by_game[r.get("эпизод")].append(r)
    executed = Counter()
    leaks = []
    for idx in sorted(by_game):
        game = sorted(by_game[idx], key=lambda r: r.get("turn_played") or 0)
        for r in game:
            city = (r.get("my_cities") or [{}])[0]
            surplus = city.get("surplus_food")
            for a in r.get("действия_за_ход") or []:
                name = str(a[2]) if len(a) > 2 else ""
                if name.startswith("city_unwork"):
                    executed["city_unwork"] += 1
                    tf = tile_food(city, name)
                    loss = tf if tf is not None else MAX_TILE_FOOD
                    if surplus is not None and float(surplus) < loss:
                        leaks.append((idx, r.get("turn"), name,
                                      f"surplus={surplus} потеря={loss}"))
                elif name.startswith("city_change_specialist"):
                    executed["city_change_specialist"] += 1
                    if surplus is not None and float(surplus) < MAX_TILE_FOOD:
                        leaks.append((idx, r.get("turn"), name,
                                      f"surplus={surplus} граница={MAX_TILE_FOOD}"))
                elif name == "join_city":
                    executed["join_city"] += 1
                    if surplus is not None and float(surplus) < FOOD_COST:
                        leaks.append((idx, r.get("turn"), name,
                                      f"surplus={surplus} food_cost={FOOD_COST}"))
    print(f"{path}: выполненных действий трёх семейств {dict(executed)}; "
          f"ПРОТЕЧЕК (запрещено, но ушло) {len(leaks)}")
    for leak in leaks[:10]:
        print("   протечка:", leak)