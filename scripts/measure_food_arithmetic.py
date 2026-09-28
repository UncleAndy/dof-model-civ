#!/usr/bin/env python
"""Арифметика еды города по ЖИВЫМ записям: правила, выход клетки, цена действия.

Печатает:

1. **Расход.** Совпадает ли `surplus_food` с `prod_food − food_cost × размер` —
   проверка правила по живым наблюдениям.
2. **Ориентация карты.** Выход клетки под городом/юнитами в обеих ориентациях.
3. **Цена действия.** Для каждого записанного `city_work/city_unwork`
   (`_idx_dx_dy`) — выход ЦЕЛЕВОЙ клетки из окна и прод-еда города до/после,
   плюс проверка «Δprod_food == ±выход клетки».
"""
import json
import sys
from collections import Counter, defaultdict

path = sys.argv[1]
rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
by_game = defaultdict(list)
for r in rows:
    by_game[r.get("эпизод")].append(r)

# ── 1. правило расхода ────────────────────────────────────────────────────────
ok = bad = 0
print(f"файл {path}: строк {len(rows)}, матчей {len(by_game)}")
for r in rows:
    fc = r.get("food_cost")
    for c in r.get("my_cities") or []:
        s, p, su = c.get("size"), c.get("prod_food"), c.get("surplus_food")
        if None in (s, p, su) or fc is None:
            continue
        if float(p) - float(fc) * float(s) == float(su):
            ok += 1
        else:
            bad += 1
            print(f"   РАСХОЖДЕНИЕ: ход {r.get('turn')} размер {s} prod {p} "
                  f"surplus {su} food_cost {fc}")
print(f"1) surplus == prod_food − food_cost×размер: совпало {ok}, разошлось {bad}; "
      f"food_cost={Counter(r.get('food_cost') for r in rows)}")

# ── 2. ориентация ─────────────────────────────────────────────────────────────
print("2) ориентация map.output:")
seen = set()
for r in rows:
    for c in (r.get("my_cities") or []):
        k = c.get("клетка_центра") or {}
        key = (str(k.get("размеры")), str(k.get("выход_xy")), str(k.get("выход_yx")))
        if key in seen:
            continue
        seen.add(key)
        print(f"   размеры={k.get('размеры')} xy={k.get('выход_xy')} "
              f"террейн_xy={k.get('террейн_xy')} yx={k.get('выход_yx')}")

# ── 3. цена действий по клеткам ───────────────────────────────────────────────
def tile_food(win, off, orient="xy"):
    cell = (win or {}).get(f"{off[0]},{off[1]}")
    if not isinstance(cell, dict):
        return None
    vec = cell.get(orient)
    if isinstance(vec, list) and vec:
        return vec[0]
    return None

print("3) действия по клеткам (city_work/city_unwork): цена клетки и еда до/после")
agree = disagree = 0
for idx in sorted(by_game):
    game = sorted(by_game[idx], key=lambda r: r.get("turn_played") or 0)
    for i, r in enumerate(game):
        acts = [a for a in (r.get("действия_за_ход") or [])
                if len(a) > 2 and str(a[2]).startswith(("city_work", "city_unwork"))]
        if not acts:
            continue
        city = (r.get("my_cities") or [{}])[0]
        win = city.get("окно_клеток")
        nxt = game[i + 1] if i + 1 < len(game) else None
        nc = ((nxt or {}).get("my_cities") or [{}])[0]
        print(f"   эпизод {idx} ход {r.get('turn')}: город=({city.get('x')},{city.get('y')}) "
              f"размер={city.get('size')} prod_food={city.get('prod_food')} "
              f"surplus={city.get('surplus_food')}")
        for a in acts:
            name = str(a[2])
            parts = name.split("_")
            try:
                off = (int(parts[-2]), int(parts[-1]))
            except Exception:  # noqa: BLE001
                off = None
            f_xy = tile_food(win, off, "xy") if off else None
            print(f"     {name} смещение={off} еда_клетки(xy)={f_xy}")
        if nxt:
            print(f"     СЛЕДУЮЩИЙ ход {nxt.get('turn')}: prod_food={nc.get('prod_food')} "
                  f"surplus={nc.get('surplus_food')} размер={nc.get('size')} "
                  f"сущ={nxt.get('obs_entities')}")
            if city.get("prod_food") is not None and nc.get("prod_food") is not None:
                d = float(nc["prod_food"]) - float(city["prod_food"])
                print(f"     Δprod_food = {d:+}")
print(f"   (сверка «Δprod_food против выхода клетки» делается глазами по строкам выше)")