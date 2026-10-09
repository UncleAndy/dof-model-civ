"""Транспонирует ли проект карту? Поведенческая проверка на настоящем захвате.

Якорь: наши юниты и город. Их (x, y) известны из секций `unit`/`city`, а слой `unit_owner` обязан
показать там наш id (0). Измерено: чтение `[x][y]` даёт 0 для всех четырёх юнитов, чтение `[y][x]` —
255. Сравниваем это с тем, что вернут САМИ функции проекта.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env import spec_collapse_candidates as C   # noqa: E402
from env import spec_threat as T                # noqa: E402


def main() -> int:
    raw = json.loads((ROOT / "tests" / "fixtures" / "real_obs_01.json").read_text("utf-8"))
    rows = [s for s in raw if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    obs = rows[-1]["observation"]
    owner = ((obs.get("map") or {}).get("unit_owner")) or []

    print("== наши юниты и город: что читает проект, что даёт измеренный порядок ==")
    same = diff = 0
    for uid, rec in (obs.get("unit") or {}).items():
        if not isinstance(rec, dict):
            continue
        x, y = int(rec.get("x") or 0), int(rec.get("y") or 0)
        direct = owner[x][y]
        project = C._cell(owner, x, y)
        mark = "совпало" if direct == project else "РАСХОЖДЕНИЕ"
        same += direct == project
        diff += direct != project
        print(f"  {uid} ({x},{y}): [x][y]={direct}, функция проекта={project} — {mark}")
    for cid, rec in (obs.get("city") or {}).items():
        if not isinstance(rec, dict):
            continue
        x, y = int(rec.get("x") or 0), int(rec.get("y") or 0)
        direct = owner[x][y]
        project = C._cell(owner, x, y)
        print(f"  город {cid} ({x},{y}): [x][y]={direct}, функция проекта={project} — "
              f"{'совпало' if direct == project else 'РАСХОЖДЕНИЕ'}")
    print(f"  итого по юнитам: совпало {same}, расхождений {diff}")

    print("\n== чужие из карты: что нашла функция проекта ==")
    found = T.foreign_units_from_map(obs, 0)
    print("  foreign_units_from_map:", found)
    direct_scan = []
    for x in range(len(owner)):
        for y in range(len(owner[x])):
            v = owner[x][y]
            if isinstance(v, int) and v not in (255, 0):
                direct_scan.append((v, x, y))
    print("  прямой скан [x][y]:", direct_scan)

    print("\n== сколько клеток вообще различает порядок ==")
    n = len(owner)
    m = len(owner[0]) if n else 0
    limit = min(n, m)
    cells = [(x, y) for x in range(limit) for y in range(limit) if owner[x][y] != owner[y][x]]
    print(f"  карта {n}x{m}; клеток, где порядки дают РАЗНОЕ: {len(cells)} из {limit ** 2}")
    print("  эти клетки (значение [x][y] против значения функции проекта):")
    for x, y in cells:
        print(f"    ({x},{y}): [x][y]={owner[x][y]}  функция={C._cell(owner, x, y)}  "
              f"владелец_клетки={C.tile_owner_at(obs, x, y)}")
    return 0


raise SystemExit(main())
