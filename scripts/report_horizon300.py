#!/usr/bin/env python
"""Разбор §10.47: три ветви × 12 игр × 300 ходов.

Правило вердикта объявлено ДО данных: требуется И абсолютная разница медиан ≥ 2 очка,
И относительная ≥ 10 % от контрольной медианы, И 95%-бутстрап-CI разности без нуля.
"""
import json
import random
import statistics
from collections import Counter, defaultdict

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
    by_game = defaultdict(list)
    for r in rows:
        by_game[r.get("эпизод")].append(r)
    cities, sizes, units, fam = [], [], [], Counter()
    contacts = deaths = 0
    for g in by_game.values():
        g.sort(key=lambda r: r.get("turn_played") or 0)
        last = g[-1]
        mc = last.get("my_cities") or []
        cities.append(len(mc))
        sizes.append(max((c.get("size") or 0) for c in mc) if mc else 0)
        units.append(len(last.get("my_units") or []))
        if any((r.get("foreign_units") or []) for r in g):
            contacts += 1
        for r in g:
            for a in r.get("действия_за_ход") or []:
                if len(a) > 2:
                    fam[family(str(a[2]))] += 1
    sc = [float(e.get("score_cum") or 0) for e in eps]
    turns = [int(e.get("turns") or 0) for e in eps]
    dec = [float(e.get("decisions_per_turn_mean") or 0) for e in eps]
    short = [t for t in turns if t < 300]
    return {"tag": tag, "sc": sc, "cities": cities, "sizes": sizes, "units": units,
            "fam": dict(fam), "dec": statistics.median(dec) if dec else 0.0,
            "short": short, "contacts": contacts, "n_games": len(by_game)}


def boot_diff(a, b, n=20000, seed=11):
    rnd = random.Random(seed)
    diffs = []
    for _ in range(n):
        da = [rnd.choice(a) for _ in a]
        db = [rnd.choice(b) for _ in b]
        diffs.append(statistics.median(da) - statistics.median(db))
    diffs.sort()
    return diffs[int(0.025 * n)], diffs[int(0.975 * n)]


def show(r):
    s = sorted(r["sc"])
    print(f"--- {r['tag']}: игр {len(r['sc'])}, коротких (<300) {len(r['short'])} {r['short']}")
    print(f"    счёт: {[round(x) for x in r['sc']]}")
    print(f"    медиана {statistics.median(s):.1f}, сумма {sum(s):.0f}, "
          f"разброс {min(s):.0f}..{max(s):.0f}")
    print(f"    городов {r['cities']} (сумма {sum(r['cities'])}), "
          f"макс.размер {r['sizes']}, юнитов {r['units']}")
    print(f"    решения/ход (медиана) {r['dec']:.2f}; игры с контактом {r['contacts']}")
    print(f"    семьи: {r['fam']}")


if __name__ == "__main__":
    base = load("БАЗА", "/tmp/h300_base.json")
    ban = load("ЗАПРЕТ Warriors", "/tmp/h300_ban.json")
    leg = load("ПРЕЖНИЙ ПУТЬ/ВЫКЛ", "/tmp/h300_legacy.json")
    for r in (base, ban, leg):
        show(r)
    print("=" * 96)
    for name, a, b in (("H1 производство полезно (база − запрет)", base, ban),
                       ("H3 расширение окупается (прежний путь − база)", leg, base)):
        ma, mb = statistics.median(a["sc"]), statistics.median(b["sc"])
        lo, hi = boot_diff(a["sc"], b["sc"])
        ok_abs = ma >= mb + 2
        ok_rel = ma >= 1.10 * mb
        ok_ci = lo > 0
        verdict = ("ПОДТВЕРЖДЕНО" if (ok_abs and ok_rel and ok_ci)
                   else "не установлено")
        print(f"{name}: медианы {ma:.1f} vs {mb:.1f} (разница {ma - mb:+.1f}, "
              f"отношение {ma / mb if mb else float('nan'):.2f}); условия: "
              f"абс {'✓' if ok_abs else '✗'}, отн {'✓' if ok_rel else '✗'}, "
              f"CI [{lo:+.1f}, {hi:+.1f}] {'✓' if ok_ci else '✗'} -> {verdict}")