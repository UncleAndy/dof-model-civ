#!/usr/bin/env python
"""Числа для защитного правила: распределение еды клеток и срабатывание правила.

1. Распределение выхода еды по клеткам вокруг наших городов — из него берётся
   НАИБОЛЬШАЯ возможная потеря еды за одно действие (граница правила, а не догадка).
2. Прямая проверка правила «запретить `city_unwork`, если `surplus_food < еда клетки`»
   на ВСЕХ записанных действиях: сколько запретило бы; и отдельно — на действиях того
   хода, после которого город погиб (правило обязано их запретить).
3. Проверка `join_city`: каким был `surplus_food` при присоединении жителя.
"""
import json
import sys
from collections import Counter, defaultdict

foods = Counter()
rows_all = []
for path in sys.argv[1:]:
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    rows_all.extend((path, r) for r in rows)

# ── 1. распределение еды клеток вокруг городов ────────────────────────────────
for path, r in rows_all:
    for c in r.get("my_cities") or []:
        win = c.get("окно_клеток") or {}
        for off, cell in win.items():
            vec = cell.get("xy") if isinstance(cell, dict) else None
            if isinstance(vec, list) and vec:
                foods[int(vec[0])] += 1
print("1) распределение еды клеток вокруг городов (значение: сколько раз):")
for f in sorted(foods):
    print(f"   еда {f}: {foods[f]}")
print(f"   максимум еды клетки = {max(foods) if foods else None}")

# ── 2. правило на записанных действиях ────────────────────────────────────────
by_game = defaultdict(list)
for path, r in rows_all:
    by_game[(path, r.get("эпизод"))].append(r)

fired = total = 0
death_fired = []
for key in sorted(by_game, key=lambda k: (k[0], k[1] or 0)):
    game = sorted(by_game[key], key=lambda r: r.get("turn_played") or 0)
    for i, r in enumerate(game):
        city = (r.get("my_cities") or [{}])[0]
        win = city.get("окно_клеток") or {}
        for a in (r.get("действия_за_ход") or []):
            name = str(a[2]) if len(a) > 2 else ""
            if not name.startswith("city_unwork"):
                continue
            parts = name.split("_")
            try:
                off = (int(parts[-2]), int(parts[-1]))
            except Exception:  # noqa: BLE001
                continue
            cell = win.get(f"{off[0]},{off[1]}")
            vec = cell.get("xy") if isinstance(cell, dict) else None
            if not isinstance(vec, list) or not vec:
                continue
            tile_food = float(vec[0])
            surplus = city.get("surplus_food")
            if surplus is None:
                continue
            total += 1
            if float(surplus) < tile_food:
                fired += 1
                nxt = game[i + 1] if i + 1 < len(game) else None
                if nxt is not None and not nxt.get("obs_entities"):
                    death_fired.append((key[1], r.get("turn"), tile_food, surplus))
print(f"2) правило «запретить city_unwork, если surplus_food < еда клетки»:")
print(f"   записанных city_unwork с известной клеткой: {total}; правило запретило бы: {fired}")
print(f"   из них на ходу перед смертью: {death_fired}")

# ── 3. join_city ──────────────────────────────────────────────────────────────
joins = Counter()
for path, r in rows_all:
    for a in (r.get("действия_за_ход") or []):
        if len(a) > 2 and str(a[2]) == "join_city":
            c = (r.get("my_cities") or [{}])[0]
            joins[(c.get("size"), c.get("surplus_food"))] += 1
print("3) join_city: (размер города, surplus_food на момент присоединения) → сколько раз")
for k in sorted(joins, key=lambda k: (k[0] or 0, k[1] or 0)):
    print(f"   размер={k[0]} surplus={k[1]}: {joins[k]}")