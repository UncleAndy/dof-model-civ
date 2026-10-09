"""Соглашение индексации слоёв карты: [x][y] или [y][x]?

Скилл стенда (`dof-model-civ`) утверждает: слои карты индексируются `[x][y]`, и ошибка чтения молча
уводит агента в другую сторону. Мой зонд сегодня читал `[y][x]`. Проверка — по НАШЕМУ юниту: его
координаты `(x, y)` известны из секции `unit`, и слой `unit_owner` обязан показать там наш id (0).
Проверяются оба прочтения сразу; верное — то, где сходится.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    raw = json.loads((ROOT / "tests" / "fixtures" / "real_obs_01.json").read_text("utf-8"))
    rows = [s for s in raw if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    obs = rows[-1]["observation"]
    mp = obs.get("map") or {}
    print("ключи map:", sorted(mp))
    print("размеры:", {k: (len(v), len(v[0]) if v and isinstance(v[0], list) else None)
                      for k, v in mp.items() if isinstance(v, list) and v})
    owner = mp.get("unit_owner")
    units = obs.get("unit") or {}
    print(f"наших юнитов в срезе: {len(units)}")
    hits_xy = hits_yx = 0
    for uid, rec in list(units.items()):
        if not isinstance(rec, dict):
            continue
        x, y = int(rec.get("x") or 0), int(rec.get("y") or 0)
        own = int(rec.get("owner", 0) or 0)
        a = owner[x][y] if x < len(owner) and y < len(owner[x]) else None
        b = owner[y][x] if y < len(owner) and x < len(owner[y]) else None
        if a == own:
            hits_xy += 1
        if b == own:
            hits_yx += 1
        print(f"  юнит {uid} в ({x},{y}) владелец {own}: [x][y]={a}  [y][x]={b}")
    print(f"\nсходится как [x][y]: {hits_xy} из {len(units)}; как [y][x]: {hits_yx} из {len(units)}")
    # Дополнительный якорь — город: слой city_owner в координатах города
    co = mp.get("city_owner")
    cities = obs.get("city") or {}
    for cid, rec in list(cities.items())[:3]:
        if not isinstance(rec, dict):
            continue
        x, y = int(rec.get("x") or 0), int(rec.get("y") or 0)
        own = int(rec.get("owner", 0) or 0)
        a = co[x][y] if co and x < len(co) and y < len(co[x]) else None
        b = co[y][x] if co and y < len(co) and x < len(co[y]) else None
        print(f"  город {cid} в ({x},{y}) владелец {own}: city_owner [x][y]={a}  [y][x]={b}")
    return 0


raise SystemExit(main())
