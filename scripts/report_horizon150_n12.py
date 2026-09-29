#!/usr/bin/env python
"""Разбор §10.44: три ветви × 12 игр × 150 ходов, правило вердикта объявлено заранее.

Метрики на игру: счёт за 150 ходов, число городов (из мира, не из действий), максимальный
размер города, юнитов в конце, семьи действий. Вердикт: медианы + 95%-бутстрап-CI разности.
"""
import json
import random
import statistics
from collections import Counter

MOVES = ("goto", "move", "road", "irrigate", "mine", "fortify", "plant", "pillage",
         "hut_enter", "explore")


def family(name: str) -> str:
    if any(name.startswith(k) for k in MOVES):
        return "движение"
    if name.startswith("produce_"):
        return "производство"
    if name == "city_buy_production":
        return "покупка"
    if name == "build_city":
        return "основание"
    if name.startswith("research"):
        return "наука"
    if name.startswith("city_"):
        return "город"
    return "прочее"


def load(tag, json_path):
    d = json.load(open(json_path))
    eps = list(d["results"].values())[0]
    rows = [json.loads(x) for x in open(f"{json_path}.state.jsonl", encoding="utf-8") if x.strip()]
    by_game = {}
    for r in rows:
        by_game.setdefault(r.get("эпизод"), []).append(r)
    games = []
    for idx, g in sorted(by_game.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        g.sort(key=lambda r: r.get("turn_played") or 0)
        last = g[-1]
        cities = last.get("my_cities") or []
        fam = Counter()
        for r in g:
            for a in r.get("действия_за_ход") or []:
                if len(a) > 2:
                    fam[family(str(a[2]))] += 1
        games.append({
            "эпизод": idx,
            "ходов": len(g),
            "городов": len(cities),
            "макс_размер": max((c.get("size") or 0) for c in cities) if cities else 0,
            "юнитов": len(last.get("my_units") or []),
            "семьи": dict(fam),
        })
    sc = [float(e.get("score_cum") or 0) for e in eps]
    dec = [float(e.get("decisions_per_turn_mean") or 0) for e in eps]
    return {"tag": tag, "games": games, "sc": sc, "dec": dec, "n": len(sc)}


def boot_diff(a, b, n=20000, seed=7):
    """95%-CI разности медиан (a − b) бутстрапом."""
    rnd = random.Random(seed)
    diffs = []
    for _ in range(n):
        da = [rnd.choice(a) for _ in a]
        db = [rnd.choice(b) for _ in b]
        diffs.append(statistics.median(da) - statistics.median(db))
    diffs.sort()
    return diffs[int(0.025 * n)], diffs[int(0.975 * n)]


def show(r):
    sc = sorted(r["sc"])
    cities = [g["городов"] for g in r["games"]]
    sizes = [g["макс_размер"] for g in r["games"]]
    units = [g["юнитов"] for g in r["games"]]
    fam = Counter()
    for g in r["games"]:
        fam.update(g["семьи"])
    print(f"--- {r['tag']} (игр {r['n']})")
    print(f"    счёт: {[round(x) for x in r['sc']]} медиана {statistics.median(sc):.1f} "
          f"сумма {sum(sc):.0f}")
    print(f"    городов: {cities} (сумма {sum(cities)}); макс.размер города: {sizes} "
          f"(медиана {statistics.median(sizes):.1f})")
    print(f"    юнитов в конце: {units} (медиана {statistics.median(units):.1f})")
    print(f"    решения/ход: медиана {statistics.median(r['dec']):.2f}")
    print(f"    семьи: {dict(fam)}")


if __name__ == "__main__":
    base = load("БАЗА", "/tmp/h150n12_base.json")
    ban = load("ЗАПРЕТ Warriors", "/tmp/h150n12_ban.json")
    leg = load("ПРЕЖНИЙ ПУТЬ/ВЫКЛ", "/tmp/h150n12_legacy.json")
    for r in (base, ban, leg):
        show(r)
    print("=" * 92)
    for name, pair in (("H1 производство полезно (база − запрет)", (base, ban)),
                       ("H3 расширение окупается (прежний путь − база)", (leg, base))):
        a, b = pair
        lo, hi = boot_diff(a["sc"], b["sc"])
        ma, mb = statistics.median(a["sc"]), statistics.median(b["sc"])
        verdict = "не установлено"
        if ma >= mb + 2 and lo > 0:
            verdict = "ПОДТВЕРЖДЕНО"
        elif mb >= ma + 2 and hi < 0:
            verdict = "ПОДТВЕРЖДЕНО в обратную сторону"
        print(f"{name}: медианы {ma:.1f} vs {mb:.1f}, CI разности [{lo:+.1f}, {hi:+.1f}] "
              f"-> {verdict}")