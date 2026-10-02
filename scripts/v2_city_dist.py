"""Измерить расстояние между нашими городами (когда основан 2-й город) по трассе.

Ищет в трассе: (1) координаты столицы — город, существующий с хода 1; (2) действия `found_city`
(эффект ("found_city", x, y)) — где основан новый город. Печатает расстояния между городами пары.

Запуск: .venv/bin/python scripts/v2_city_dist.py knowledge/traces_cap.jsonl [ещё_трассы...]
"""
from __future__ import annotations

import json
import sys

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brain.v2.threat import cheb  # noqa: E402


def analyze(path: str) -> None:
    capitals: dict[str, tuple] = {}        # eid -> (x, y) города, видимого с начала
    founding: list[tuple] = []             # (ход, x, y) найденных городов
    first_turn: int | None = None
    seen_cities: dict[str, tuple] = {}
    for line in open(path, errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if "решение" not in r:
            continue
        # координаты всех наших городов из наблюдения недоступны напрямую в трассе,
        # поэтому ищем по эффектам действий: found_city даёт точку основания
        ch = r.get("выбрано")
        if ch and ch.get("steps", []) and ch["steps"][0].get("ctrl") == "unit" \
                and ch["steps"][0].get("action") == "build_city":
            eff = ch.get("effect") or ()
            if len(eff) == 3 and isinstance(eff[1], int) and isinstance(eff[2], int):
                founding.append((r.get("ход"), eff[1], eff[2]))
    if first_turn is None:
        first_turn = 1
    print(f"\n{path}: оснований городов найдено: {len(founding)}")
    xs = [f[1] for f in founding]
    ys = [f[2] for f in founding]
    for i in range(len(founding)):
        for j in range(i + 1, len(founding)):
            (t1, x1, y1), (t2, x2, y2) = founding[i], founding[j]
            print(f"  город {i + 1} (ход {t1}, {x1},{y1}) ~ город {j + 1} (ход {t2}, {x2},{y2}): "
                  f"чебышёв {cheb(x1, y1, x2, y2, 78)}")
    if len(founding) >= 1:
        print(f"  точки основания: {founding}")


def main() -> int:
    paths = sys.argv[1:] or ["knowledge/traces_cap.jsonl"]
    for p in paths:
        analyze(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())