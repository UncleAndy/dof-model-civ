#!/usr/bin/env python
"""Почему счёт ветвей расходится: устойчивость решений, а не их количество.

Механизм из серии 2026-09-27: ветвь ВКЛ отдаёт БОЛЬШЕ действий за ход (1.21 против
0.91), но получает МЕНЬШИЙ серверный счёт. Правдоподобное объяснение — «чехарда
производства»: прогноз переоценивает город каждый ход и переключает его очередь,
поэтому ничего не успевает достроиться (в игре это потерянные щиты и отсутствие
городов/юнитов, то есть и счёта).

Здесь это измеряется описательно, без порогов и без вердикта:

* для каждой игры — доля решений, которые МЕНЯЮТ уже принятое для того же актора
  (город/юнит) решение;
* для городов отдельно — сколько раз очередь производства менялась между ходами и
  сколько раз подряд держалась;
* сколько городов появилось в наблюдении (evidence of completed builds, косвенно).

Порогов не объявляем: это разбор механизма, а вердикт серии считается отдельно.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter


def load(path):
    doc = json.load(open(path, encoding="utf-8"))
    results = doc.get("results") or {}
    rows = []
    for agent, entries in results.items():
        for entry in (entries if isinstance(entries, list) else [entries]):
            if isinstance(entry, dict):
                rows.append(entry)
    return rows


def production_series(row):
    """[(ctrl, actor, name)] для решений управления городом — в порядке ходов."""
    return [tuple(d) for d in (row.get("decisions") or [])
            if isinstance(d, (list, tuple)) and len(d) == 3 and d[0] == "city"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--on", nargs="+", required=True)
    parser.add_argument("--off", nargs="+", required=True)
    args = parser.parse_args()

    for arm, paths in (("ВКЛ", args.on), ("ВЫКЛ", args.off)):
        rows = []
        for path in paths:
            rows.extend(load(path))
        good = [r for r in rows if int(r.get("actions_issued") or 0) > 0]
        switches, totals, runs, cities = [], [], [], []
        kinds = Counter()
        for row in good:
            series = production_series(row)
            kinds.update(d[2] for d in (row.get("decisions") or [])
                         if isinstance(d, (list, tuple)) and len(d) == 3)
            if not series:
                continue
            changes = sum(1 for a, b in zip(series, series[1:])
                          if a[1:] != b[1:])
            switches.append(changes)
            totals.append(len(series))
            # длины непрерывных участков одной и той же очереди
            length = 1
            for a, b in zip(series, series[1:]):
                if a[1:] == b[1:]:
                    length += 1
                else:
                    runs.append(length)
                    length = 1
            runs.append(length)
            cities.append(row.get("entity_kinds_max", {}).get("city", 0))
        print(f"\n=== {arm} (игр с действиями: {len(good)})")
        if switches:
            print(f"  решений по городам за игру: медиана "
                  f"{statistics.median(totals):.0f}")
            print(f"  смен очереди за игру: медиана {statistics.median(switches):.0f} "
                  f"(доля смен от решений: "
                  f"{sum(switches) / sum(totals):.0%})")
            print(f"  длина непрерывного удержания очереди: медиана "
                  f"{statistics.median(runs):.1f}, максимум {max(runs)}")
            print(f"  городов в наблюдении: медиана {statistics.median(cities):.0f}, "
                  f"максимум {max(cities)}")
        top = ", ".join(f"{name} {count}" for name, count in kinds.most_common(6))
        print(f"  частые действия: {top}")
        units = [int(r.get("entity_kinds_max", {}).get("unit", 0)) for r in good]
        cities_all = [int(r.get("entity_kinds_max", {}).get("city", 0)) for r in good]
        score_events = [int(r.get("score_events") or 0) for r in good]
        print(f"  юнитов в наблюдении (максимум за игру): медиана "
              f"{statistics.median(units):.0f}, максимум {max(units)}")
        print(f"  городов в наблюдении: медиана {statistics.median(cities_all):.0f}, "
              f"максимум {max(cities_all)}")
        print(f"  событий счёта (серверных надбавок): медиана "
              f"{statistics.median(score_events):.0f}, максимум {max(score_events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
