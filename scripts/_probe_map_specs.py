"""Справочники мира и окрестность нашего города: чем опознать «океан» и «реку».

Вид 14 (приморье) и вид 22 (река) ссылаются на клетку, а не на постройку. Чтобы оценить их, нужны
два имени: какой `terrain`-id есть океан и какой `extras`-id есть река. Они берутся из того, что
опубликовал мир, а не из памяти о правилах.
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    raw = json.loads((ROOT / "tests" / "fixtures" / "real_obs_01.json").read_text("utf-8"))
    rows = [s for s in raw if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    obs = rows[-1]["observation"]
    print("секции захвата:", sorted(obs))

    mp = obs.get("map") or {}
    terrain, extras = mp.get("terrain") or [], mp.get("extras") or []
    print(f"карта: terrain {len(terrain)} строк, extras {len(extras)} строк")
    if terrain:
        print("  terrain[0][:12]:", terrain[0][:12])
    if extras:
        print("  extras[y][x] — маска длиной", len(extras[0][0]) if extras[0] else 0)
        per_id = collections.Counter()
        for row in extras:
            for cell in (row if isinstance(row, list) else []):
                if isinstance(cell, list):
                    for i, on in enumerate(cell):
                        if on:
                            per_id[i] += 1
        print("  extras: плиток с каждым id (топ-8):", dict(per_id.most_common(8)))
        print("  extras: плиток с id 1:", per_id.get(1, 0), "| с id 13:", per_id.get(13, 0))
    flat_t = [t for row in terrain for t in (row if isinstance(row, list) else [row])]
    land = [t for t in flat_t if t != 255]
    print("  terrain: известно плиток", len(land), "из", len(flat_t),
          "| распределение (топ-8):", dict(collections.Counter(land).most_common(8)))

    city = None
    for cid, rec in (obs.get("city") or {}).items():
        if isinstance(rec, dict) and int(rec.get("owner", 0) or 0) == 0:
            city = (cid, rec)
            break
    if not city:
        print("своего города нет")
        return 0
    cid, rec = city
    cx, cy = int(rec.get("x") or 0), int(rec.get("y") or 0)
    print(f"\nнаш город {cid} ({cx},{cy}); имя {rec.get('name')}")
    mask = rec.get("improvements") or []
    built = [i for i, on in enumerate(mask) if on]
    print(f"  построено в городе (индексы маски): {built} из {len(mask)}")
    # СЛОИ ИНДЕКСИРУЮТСЯ [x][y] — проверено на наших юнитах (4 из 4) и городе.
    known_all = sum(1 for x in range(len(terrain)) for y in range(len(terrain[x]))
                    if isinstance(terrain[x][y], int) and terrain[x][y] != 255)
    print(f"  известно плиток во всём срезе: {known_all}")
    known_near = 0
    lines = []
    for dy in range(-2, 3):
        row = []
        for dx in range(-2, 3):
            x, y = cx + dx, cy + dy
            if 0 <= x < len(terrain) and 0 <= y < len(terrain[x]):
                t = terrain[x][y]
                cell = extras[x][y] if x < len(extras) and y < len(extras[x]) else []
                ids = [i for i, on in enumerate(cell) if on] if isinstance(cell, list) else []
                if isinstance(t, int) and t != 255:
                    known_near += 1
                row.append(f"{t}{'+' + ','.join(map(str, ids)) if ids else ''}")
            else:
                row.append("..")
        lines.append(row)
    print(f"  из 25 клеток окрестности (радиус 2) разведано: {known_near}")
    for row in lines:
        print("   ", " ".join(f"{v:>10}" for v in row))
    # Есть ли в захвате справочник имён местности/ресурсов вообще
    for key in ("terrain", "extras", "ruleset", "settings", "improvement", "unit_type"):
        v = obs.get(key)
        if v is not None:
            print(f"  секция {key}: {type(v).__name__} {len(v) if hasattr(v, '__len__') else ''}")
    return 0


raise SystemExit(main())
