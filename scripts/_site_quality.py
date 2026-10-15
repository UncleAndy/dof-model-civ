"""§13.421: качество площадок и использование клеток — по одному сейву, по всем сторонам.

Что считаем (террейн — по правилам мира, улучшения сейв не хранит):

* `использовано от лучшего` — сколько еды+щитов дают ОБРАБОТАННЫЕ клетки города против суммы
  лучших `N` клеток в радиусе 2 (N = число обработанных). Это про расстановку жителей: 100%
  значит «город работает ровно по лучшим доступным клеткам».
* `выход` — фактические еда+щиты обработанных клеток и потолок рядом с городом. Потолок — мера
  КАЧЕСТВА ПЛОЩАДКИ: у нас город в бедном месте, если потолок низкий.

Запуск:  .venv/bin/python scripts/_site_quality.py /tmp/save_XXX.txt
"""

from __future__ import annotations

import pathlib
import re
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from brain.ai_default.tile_outputs import tile_outputs_from_rules   # noqa: E402
from env.city_vector import parse_player_section as parse_player    # noqa: E402

_ID = {"a": "Glacier", "t": "Tundra", "d": "Desert", "p": "Plains", "g": "Grassland",
       "f": "Forest", "h": "Hills", "m": "Mountains", "j": "Jungle", "s": "Swamp",
       " ": "Ocean", "+": "Lake", ":": "Deep Ocean", "i": "Inaccessible"}


def main(path: str) -> int:
    text = pathlib.Path(path).read_text(encoding="utf-8")
    rows = {int(m.group(1)): m.group(2)
            for m in re.finditer(r'^t(\d{4})="(.*)"$', text, re.M)}
    owner: dict[tuple[int, int], str] = {}
    for m in re.finditer(r'^owner(\d{4})="([^"]*)"$', text, re.M):
        y = int(m.group(1))
        for x, v in enumerate(m.group(2).split(",")):
            owner[(x, y)] = v
    worked: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for m in re.finditer(r'^worked(\d{4})="([^"]*)"$', text, re.M):
        y = int(m.group(1))
        for x, v in enumerate(m.group(2).split(",")):
            if v not in ("-", ""):
                worked[v].append((x, y))

    def terrain(x: int, y: int) -> str:
        line = rows.get(y) or " "
        return _ID.get(line[x % len(line)], "Ocean")

    def yields(x: int, y: int) -> tuple[float, float]:
        got = tile_outputs_from_rules(terrain(x, y)) or (0.0, 0.0, 0.0)
        return float(got[0]), float(got[1])

    for player in range(6):
        try:
            cities = parse_player(text, player)
        except Exception:  # noqa: BLE001
            continue
        if not cities:
            continue
        eff: list[float] = []
        cells_n: list[int] = []
        got_all: list[float] = []
        best_all: list[float] = []
        sh_all: list[float] = []
        sh_best_all: list[float] = []
        for cid, city in cities.items():
            cells = worked.get(str(cid)) or []
            if not cells:
                continue
            cx, cy = int(city["x"]), int(city["y"])
            got = sum(sum(yields(x, y)) for x, y in cells)
            sh = sum(yields(x, y)[1] for x, y in cells)
            cand: list[float] = []
            cand_sh: list[float] = []
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    x, y = cx + dx, cy + dy
                    if y not in rows or x >= len(rows[y]):
                        continue
                    if owner.get((x, y), "-") not in ("-", str(player)):
                        continue
                    cand.append(sum(yields(x, y)))
                    cand_sh.append(yields(x, y)[1])
            cand.sort(reverse=True)
            cand_sh.sort(reverse=True)
            best = sum(cand[:len(cells)])
            eff.append(got / max(best, 0.001))
            cells_n.append(len(cells))
            got_all.append(got)
            best_all.append(best)
            sh_all.append(sh)
            sh_best_all.append(sum(cand_sh[:len(cells)]))
        if not eff:
            continue
        n = len(eff)
        print(f"игрок {player}: городов {n}, использовано от лучшего {sum(eff)/n*100:.0f}%, "
              f"клеток/город {sum(cells_n)/n:.1f}, выход {sum(got_all)/n:.1f} "
              f"из потолка {sum(best_all)/n:.1f} | ЩИТЫ {sum(sh_all)/n:.2f} "
              f"из потолка {sum(sh_best_all)/n:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/dof_last_save.txt"))
