#!/usr/bin/env python
"""Разбор §10.42: база против запрета производства на 150 ходах.

Считается по записям обеих ветвей: основано городов, движение/работы, решений за ход,
счёт (сумма, на игру, медиана), смерти (короткие игры), максимум юнитов на одной клетке.
"""
import glob
import json
import statistics
from collections import Counter

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
    return f"прочее:{name.split('_')[0] if name else '?'}"


def arm(tag, json_path):
    try:
        data = json.load(open(json_path))
    except FileNotFoundError:
        print(f"{tag}: нет файла {json_path}")
        return None
    eps = list(data["results"].values())[0]
    rows = []
    for line in open(f"{json_path}.state.jsonl", encoding="utf-8"):
        if line.strip():
            rows.append(json.loads(line))
    by_game = {}
    for r in rows:
        by_game.setdefault(r.get("эпизод"), []).append(r)
    fam = Counter()
    cities = 0
    stacked = []
    for idx, game in by_game.items():
        game.sort(key=lambda r: r.get("turn_played") or 0)
        for r in game:
            for a in r.get("действия_за_ход") or []:
                name = str(a[2]) if len(a) > 2 else ""
                f = family(name)
                fam[f] += 1
                if f == "основание города":
                    cities += 1
        last = game[-1]
        units = last.get("my_units") or []
        if units:
            pos = Counter((u.get("x"), u.get("y")) for u in units)
            stacked.append(max(pos.values()))
    turns = [int(e.get("turns") or 0) for e in eps]
    dec = [float(e.get("decisions_per_turn_mean") or 0) for e in eps]
    sc = [float(e.get("score_cum") or 0) for e in eps]
    print("=" * 92)
    print(f"{tag}: игр {len(eps)}, коротких (<150) {sum(1 for t in turns if t < 150)}")
    print(f"   ходы: {turns}")
    print(f"   семьи: {dict(fam)}")
    print(f"   основано городов: {cities}")
    print(f"   счёт: сумма {sum(sc):.0f}, на игру "
          f"{[round(x, 1) for x in sc]}, медиана {sorted(sc)[len(sc)//2]:.0f}")
    print(f"   решений/ход: среднее {statistics.mean(dec):.2f} (мин {min(dec):.2f})")
    print(f"   максимум юнитов на клетке: {stacked}")
    return {"cities": cities, "score": sum(sc), "dec": statistics.mean(dec),
            "families": dict(fam), "turns": turns}


if __name__ == "__main__":
    base = arm("БАЗА (150 ходов)", "/tmp/h150_base.json")
    ban = arm("ЗАПРЕТ Warriors (150 ходов)", "/tmp/h150_ban.json")
    leg = arm("ПРЕЖНИЙ ПУТЬ/ВЫКЛ (150 ходов, двигается и основывает)",
              "/tmp/h150_legacy.json")
    if base and ban and leg:
        print("=" * 92)
        print(f"ИТОГ: городов база {base['cities']} | запрет {ban['cities']} | "
              f"прежний путь {leg['cities']}")
        print(f"      счёт  база {base['score']:.0f} | запрет {ban['score']:.0f} | "
              f"прежний путь {leg['score']:.0f}")
        print(f"      движение/работы база {base['families'].get('движение/работы', 0)} | "
              f"запрет {ban['families'].get('движение/работы', 0)} | "
              f"прежний путь {leg['families'].get('движение/работы', 0)}")
        print("Ожидание §10.43: если расширение окупается — у прежнего пути "
              "≥2 городов на игру и счёт ≥ базового")