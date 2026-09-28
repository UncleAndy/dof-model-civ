#!/usr/bin/env python
"""Цепочка еды одного матча: что именно опустило еду ниже нуля (по записям).

Печатает по ходам: размер, prod_food, surplus, и для каждого действия того хода —
выход ЦЕЛЕВОЙ клетки (из окна) — чтобы видеть, какое действие и на сколько
уменьшило еду. Плюс сообщения мира.
"""
import json
import sys

path = sys.argv[1]
wanted = int(sys.argv[2]) if len(sys.argv) > 2 else 3
rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
game = sorted([r for r in rows if r.get("эпизод") == wanted],
              key=lambda r: r.get("turn_played") or 0)
print(f"{path} эпизод {wanted}: строк {len(game)}")
for r in game:
    city = (r.get("my_cities") or [{}])[0]
    win = city.get("окно_клеток") or {}
    print("-" * 96)
    print(f"ход {r.get('turn')} сущ={r.get('obs_entities')} "
          f"город=({city.get('x')},{city.get('y')}) размер={city.get('size')} "
          f"prod_food={city.get('prod_food')} склад={city.get('food_stock')} "
          f"surplus={city.get('surplus_food')} недов={city.get('ppl_unhappy')} "
          f"food_cost={r.get('food_cost')}")
    units = [(u.get("type"), u.get("x"), u.get("y")) for u in r.get("my_units") or []]
    print(f"   юниты: {units}")
    ctrl = r.get("controller") or {}
    print(f"   клиент: городов={ctrl.get('городов_контроллер')} "
          f"юнитов={ctrl.get('юнитов_контроллер')} "
          f"поселенцы={ctrl.get('есть_поселенцы')} разбит={ctrl.get('разбит')}")
    for a in (r.get("действия_за_ход") or []):
        name = str(a[2]) if len(a) > 2 else ""
        extra = ""
        if name.startswith(("city_work", "city_unwork")):
            parts = name.split("_")
            try:
                off = (int(parts[-2]), int(parts[-1]))
            except Exception:  # noqa: BLE001
                off = None
            if off:
                cell = win.get(f"{off[0]},{off[1]}")
                vec = (cell or {}).get("xy") if isinstance(cell, dict) else None
                extra = f"  цель=({off[0]},{off[1]}) выход_клетки={vec}"
        print(f"   действие: {a[0]}/{a[1]}/{name}{extra}")
    if r.get("messages"):
        print(f"   сообщения: {r.get('messages')}")