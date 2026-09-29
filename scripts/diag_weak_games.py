#!/usr/bin/env python
"""Разбор слабых игр по уже собранным срезам: что именно теряется и когда.

Печатает таймлайн: города (id/размер/еда), юниты, чужое рядом, и все сообщения мира,
похожие на событие (голод, гибель, захват, разорение). Ничего не запускает.
"""
import json
import sys
from collections import defaultdict

KEYWORDS = ("famine", "destroy", "captur", "razed", "lost", "disband", "conquer",
            "sacked", "starved", "extinct", "eliminat", "war", "peace", "ceasefire")


def main() -> int:
    path = sys.argv[1]
    eps = [int(x) for x in sys.argv[2:]] or []
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    by = defaultdict(list)
    for r in rows:
        by[r.get("эпизод")].append(r)
    print(f"файл {path}: групп {len(by)}, игр {len(eps) if eps else 'все'}")
    for idx, g in sorted(by.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        if eps and idx not in eps:
            continue
        g.sort(key=lambda r: r.get("turn_played") or 0)
        print("=" * 90)
        print(f"ИГРА {idx}: ходов {len(g)}, счёт {g[-1].get('score')!r}, "
              f"еда-цена {g[-1].get('food_cost')!r}")
        prev = None
        for r in g:
            cities = [(c.get("id"), c.get("size"), c.get("food_stock"),
                       c.get("surplus_food")) for c in (r.get("my_cities") or [])]
            units = len(r.get("my_units") or [])
            foreign = len(r.get("foreign_units") or [])
            key = (tuple(cities), units, foreign)
            msg = str(r.get("messages") or "")
            hits = [w for w in KEYWORDS if w in msg.lower()]
            if key != prev or hits:
                line = (f"  ход {r.get('turn_played'):>4} | города {cities} | юнитов {units} "
                        f"| чужих {foreign}")
                print(line)
                if hits:
                    clean = " ".join(msg.replace("<SEP>", " ").split())
                    print(f"        события {hits}: {clean[:300]}")
                prev = key
        last = g[-1]
        print(f"  итог: города {[(c.get('id'), c.get('size')) for c in (last.get('my_cities') or [])]}, "
              f"действия за последний ход {last.get('действия_за_ход')!r}")
        # сколько ходов подряд город был без еды
        nofood = sum(1 for r in g
                     if (r.get("my_cities") or [])
                     and all((c.get("surplus_food") or 0) <= 0 for c in r["my_cities"]))
        empty = sum(1 for r in g if not (r.get("my_cities") or []))
        print(f"  ходов с surplus_food <= 0: {nofood} из {len(g)}; ходов без городов: {empty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())