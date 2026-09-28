#!/usr/bin/env python
"""Числа предложенного защитного правила (Правило F) на записях серии.

Считается по ЖИВЫМ записям прибора `--dump-state` (окно клеток вокруг городов):

1. Распределение еды клеток вокруг городов → наибольшая возможная потеря еды за одно
   действие (это граница консервативной ветви правила, а не догадка).
2. Сколько записанных действий каждого семейства правило запретило бы:
   - `city_unwork_*` — если `surplus_food − еда_целевой_клетки < 0`;
   - `join_city` — если `surplus_food < food_cost` (присоединение = +1 житель = +food_cost
     расхода);
   - `city_change_specialist_*` — если `surplus_food < max_еда_клетки` (цена неизвестна
     из имени: консервативная граница «даже худшая потеря не уводит еду в минус»).
3. По каждой погибшей игре — что было в последнем ходу и что правило запретило бы.
"""
import json
import sys
from collections import Counter, defaultdict

paths = sys.argv[1:]
rows_all = []
for path in paths:
    for line in open(path, encoding="utf-8"):
        if line.strip():
            rows_all.append((path, json.loads(line)))

# ── 1. еда клеток вокруг городов ──────────────────────────────────────────────
foods = Counter()
for _path, r in rows_all:
    for c in r.get("my_cities") or []:
        for off, cell in (c.get("окно_клеток") or {}).items():
            vec = (cell or {}).get("xy") if isinstance(cell, dict) else None
            if isinstance(vec, list) and vec:
                foods[int(vec[0])] += 1
max_food = max(foods) if foods else None
print(f"1) еда клеток вокруг городов: {dict(sorted(foods.items()))}  "
      f"клеток {sum(foods.values())}  максимум {max_food}")

by_game = defaultdict(list)
for path, r in rows_all:
    by_game[(path, r.get("эпизод"))].append(r)

def tile_food(city, name):
    parts = str(name).split("_")
    try:
        off = (int(parts[-2]), int(parts[-1]))
    except Exception:  # noqa: BLE001
        return None
    cell = (city.get("окно_клеток") or {}).get(f"{off[0]},{off[1]}")
    vec = (cell or {}).get("xy") if isinstance(cell, dict) else None
    return float(vec[0]) if isinstance(vec, list) and vec else None

counts = Counter()
fatal_hits = []
for key in sorted(by_game, key=lambda k: (k[0], k[1] or 0)):
    game = sorted(by_game[key], key=lambda r: r.get("turn_played") or 0)
    for i, r in enumerate(game):
        city = (r.get("my_cities") or [{}])[0]
        surplus = city.get("surplus_food")
        nxt = game[i + 1] if i + 1 < len(game) else None
        died_next = bool(nxt is not None and not nxt.get("obs_entities"))
        for a in (r.get("действия_за_ход") or []):
            name = str(a[2]) if len(a) > 2 else ""
            if name.startswith("city_unwork"):
                tf = tile_food(city, name)
                if tf is None or surplus is None:
                    counts["unwork_без_данных"] += 1
                    continue
                counts["unwork_всего"] += 1
                if float(surplus) < tf:
                    counts["unwork_запретило_бы"] += 1
                    if died_next:
                        fatal_hits.append((key[1], r.get("turn"), "unwork",
                                           f"surplus={surplus} еда_клетки={tf}",
                                           "город погиб на следующем ходу"))
            elif name == "join_city":
                if surplus is None:
                    counts["join_без_данных"] += 1
                    continue
                counts["join_всего"] += 1
                if float(surplus) < 2.0:
                    counts["join_запретило_бы"] += 1
                    if died_next:
                        fatal_hits.append((key[1], r.get("turn"), "join",
                                           f"surplus={surplus} размер={city.get('size')}",
                                           "город погиб на следующем ходу"))
            elif name.startswith("city_change_specialist"):
                if surplus is None:
                    counts["spec_без_данных"] += 1
                    continue
                counts["spec_всего"] += 1
                if float(surplus) < float(max_food or 3):
                    counts["spec_запретило_бы"] += 1
                    if died_next:
                        fatal_hits.append((key[1], r.get("turn"), "change_specialist",
                                           f"surplus={surplus}",
                                           "город погиб на следующем ходу"))
print("2) что правило запретило бы на записях:")
for k in ("unwork_всего", "unwork_запретило_бы", "unwork_без_данных",
          "join_всего", "join_запретило_бы", "join_без_данных",
          "spec_всего", "spec_запретило_бы", "spec_без_данных"):
    if counts[k]:
        print(f"   {k}: {counts[k]}")
print(f"3) запрещённые действия в ходу перед смертью: {fatal_hits}")

# ── 4. итог по играм ──────────────────────────────────────────────────────────
died = [k for k in by_game if any(not r.get("obs_entities") for r in by_game[k])]
print(f"4) игр {len(by_game)}, погибло {len(died)}: "
      f"{sorted((k[1] for k in died))}")
for key in sorted(died, key=lambda k: k[1] or 0):
    game = sorted(by_game[key], key=lambda r: r.get("turn_played") or 0)
    last_ok = None
    for r in game:
        if r.get("obs_entities"):
            last_ok = r
    c = ((last_ok or {}).get("my_cities") or [{}])[0]
    print(f"   игра {key[1]}: последнее наблюдение ход {(last_ok or {}).get('turn')} "
          f"размер={c.get('size')} prod_food={c.get('prod_food')} "
          f"surplus={c.get('surplus_food')} "
          f"сообщения={str((last_ok or {}).get('messages'))[-120:]!r}")