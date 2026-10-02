"""Проверка: доводятся ли постройки города до конца (щиты и срок по ходам).

Читает `knowledge/city_growth.jsonl` (пишется каждым прогоном) и показывает по каждому городу
последовательность (ход, щиты, дней_до_постройки) — видно, растут ли щиты и падает ли срок,
или город «топчется» на месте из-за смены производства.

Запуск: .venv/bin/python scripts/v2_build_progress.py knowledge/city_growth.jsonl [последние_строк]
"""
from __future__ import annotations

import collections
import json
import sys


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/city_growth.jsonl"
    tail = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rows = []
    for line in open(path, errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    rows = rows[-tail:]
    by_city: dict[str, list] = collections.defaultdict(list)
    for r in rows:
        by_city[str(r.get("город"))].append(r)
    print(f"строк: {len(rows)}; городов: {len(by_city)}")
    for city, v in sorted(by_city.items())[:4]:
        seq = [(r.get("ход"), r.get("щиты"), r.get("дней_до_постройки"), r.get("размер")) for r in v]
        print(f"\n{city}: {len(v)} наблюдений")
        print("  (ход, щиты, срок, размер):", seq[:24])
        shields = [x[1] for x in seq if isinstance(x[1], int)]
        etas = [x[2] for x in seq if isinstance(x[2], int)]
        if shields:
            print(f"  щиты: мин {min(shields)}, макс {max(shields)}, последние {shields[-8:]}")
        if etas:
            print(f"  срок: мин {min(etas)}, макс {max(etas)}, последние {etas[-8:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())