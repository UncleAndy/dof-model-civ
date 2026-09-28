#!/usr/bin/env python
"""Движение и другие семьи действий во ВСЕХ записях: старых и новых.

Вопрос Andy: не обнаружил ли я «0 движений» там, где это было и раньше, и не победили ли
мы бездействие уже. Бездействие («нет решений вовсе») и «нет движения» — РАЗНЫЕ вещи, и
здесь они считаются раздельно, по каждому файлу записей.
"""
import glob
import json
import sys
from collections import Counter, defaultdict

MOVES = ("goto", "move", "road", "irrigate", "mine", "fortify", "plant", "pillage",
         "hut_enter", "explore")


def family(name: str) -> str:
    if any(name.startswith(k) for k in MOVES):
        return "движение/работы"
    if name.startswith("produce_"):
        return "производство"
    if name == "city_buy_production":
        return "покупка"
    if name == "build_city":
        return "основание города"
    if name.startswith("research"):
        return "наука"
    if name.startswith("city_"):
        return "прочее по городу"
    if name.startswith(("join_city",)):
        return "join_city"
    return f"прочее:{name.split('_')[0] if name else '?'}"


files = sys.argv[1:] or sorted(glob.glob("/tmp/*.state.jsonl"))
for path in files:
    try:
        rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        continue
    if not rows:
        continue
    by_game = defaultdict(list)
    for r in rows:
        by_game[r.get("эпизод")].append(r)
    fam = Counter()
    games_with_move = 0
    games = 0
    turns_total = 0
    stacked = []
    for idx in sorted(by_game, key=lambda k: k if isinstance(k, int) else 0):
        game = sorted(by_game[idx], key=lambda r: r.get("turn_played") or 0)
        if not game:
            continue
        games += 1
        turns_total += len(game)
        moved = 0
        for r in game:
            for a in r.get("действия_за_ход") or []:
                name = str(a[2]) if len(a) > 2 else ""
                f = family(name)
                fam[f] += 1
                if f == "движение/работы":
                    moved += 1
        if moved:
            games_with_move += 1
        last = game[-1]
        units = last.get("my_units") or []
        if units:
            pos = Counter((u.get("x"), u.get("y")) for u in units)
            stacked.append(max(pos.values()))
    print(f"{path.split('/')[-1]}: игр {games}, ходов {turns_total}, "
          f"игр с движением {games_with_move}")
    print(f"   семьи: {dict(fam)}")
    if stacked:
        print(f"   максимум юнитов на одной клетке (последний ход игр): "
              f"{stacked}")