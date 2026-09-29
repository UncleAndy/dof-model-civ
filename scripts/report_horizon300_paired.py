#!/usr/bin/env python
"""Разбор §10.48: сопоставленные карты. 3 ветви × 12 карт (mapseed 9000+i) × 300 ходов.

Вердикт: медиана попарных разностей ≥ 2 очка И ≥ 10 % контрольной медианы И знаковый тест
(односторонний) ≥ 10 из 12 карт в пользу опытной ветви.
"""
import json
import math
import random
import statistics
from collections import Counter, defaultdict

MOVES = ("goto", "move", "road", "irrigate", "mine", "fortify", "plant", "pillage",
         "hut_enter", "explore")
TURNS = 300


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


def load(tag, path):
    d = json.load(open(path))
    eps = list(d["results"].values())[0]
    rows = [json.loads(x) for x in open(f"{path}.state.jsonl", encoding="utf-8") if x.strip()]
    by_game = defaultdict(list)
    for r in rows:
        by_game[r.get("эпизод")].append(r)
    fam = Counter()
    cities, sizes, deaths = [], [], 0
    for g in by_game.values():
        g.sort(key=lambda r: r.get("turn_played") or 0)
        mc = g[-1].get("my_cities") or []
        cities.append(len(mc))
        sizes.append(max((c.get("size") or 0) for c in mc) if mc else 0)
        for r in g:
            for a in r.get("действия_за_ход") or []:
                if len(a) > 2:
                    fam[family(str(a[2]))] += 1
    sc = [float(e.get("score_cum") or 0) for e in eps]
    turns = [int(e.get("turns") or 0) for e in eps]
    errs = [str(e.get("error") or "") for e in eps]
    return {"tag": tag, "sc": sc, "cities": cities, "sizes": sizes, "fam": dict(fam),
            "deaths": sum(1 for t in turns if t < TURNS), "turns": turns, "errs": errs,
            "dec": statistics.median([float(e.get("decisions_per_turn_mean") or 0)
                                      for e in eps])}


def complete_pairs(arms):
    """Оставить только игры, где НИ ОДНА ветвь не отказала приборно.

    Правило объявлено до данных: приборным отказом считается непустое поле
    `error` (обрыв бюджета времени или падение в библиотеке). Игра, закончившаяся
    рано БЕЗ ошибки, — это исход (например, гибель цивилизации), и она остаётся:
    выкидывать её значило бы прятать настоящие потери.
    """
    n = min(len(a["sc"]) for a in arms)
    keep, dropped = [], []
    for i in range(n):
        why = [f"{a['tag']}:{a['errs'][i]}" for a in arms if a["errs"][i]]
        if why:
            dropped.append((i + 1, why))
        else:
            keep.append(i)
    return keep, dropped


def sign_p(k, n):
    """Односторонний знаковый тест: P(X >= k) при X ~ Bin(n, 1/2)."""
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n


def boot_med(d, n=20000, seed=13):
    rnd = random.Random(seed)
    v = sorted(statistics.median([rnd.choice(d) for _ in d]) for _ in range(n))
    return v[int(0.025 * n)], v[int(0.975 * n)]


def verdict(exp, ctrl, name, idx=None):
    if idx is None:
        idx = list(range(min(len(exp["sc"]), len(ctrl["sc"]))))
    d = [exp["sc"][i] - ctrl["sc"][i] for i in idx]
    med = statistics.median(d)
    cm = statistics.median([ctrl["sc"][i] for i in idx])
    wins = sum(1 for x in d if x > 0)
    ties = sum(1 for x in d if x == 0)
    k = wins
    nn = len(d) - ties
    p = sign_p(k, nn) if nn else 1.0
    lo, hi = boot_med(d)
    ok_abs = med >= 2.0
    ok_rel = med >= 0.10 * cm
    ok_sign = p < 0.05 and wins > (len(d) - ties) / 2
    print(f"{name}: пар {len(d)}, разности {[round(x) for x in d]}")
    print(f"    медиана разности {med:+.1f} (контрольная медиана {cm:.1f}); "
          f"выигрышей {k} из {nn} (знаковый p={p:.3f}); CI медианы разности "
          f"[{lo:+.1f}, {hi:+.1f}]")
    print(f"    условия: абс {'✓' if ok_abs else '✗'}, отн {'✓' if ok_rel else '✗'}, "
          f"знаки {'✓' if ok_sign else '✗'} -> "
          f"{'ЭФФЕКТ УСТАНОВЛЕН' if (ok_abs and ok_rel and ok_sign) else 'НЕ УСТАНОВЛЕН'}")


if __name__ == "__main__":
    import sys
    PRE = sys.argv[1] if len(sys.argv) > 1 else "h300q"
    base = load("БАЗА", f"/tmp/{PRE}_base.json")
    ban = load("ЗАПРЕТ Warriors", f"/tmp/{PRE}_ban.json")
    leg = load("ПРЕЖНИЙ ПУТЬ/ВЫКЛ", f"/tmp/{PRE}_legacy.json")
    for r in (base, ban, leg):
        s = sorted(r["sc"])
        print(f"--- {r['tag']}: счёт {[round(x) for x in r['sc']]}")
        print(f"    медиана {statistics.median(s):.1f}, сумма {sum(s):.0f}, "
              f"разброс {min(s):.0f}..{max(s):.0f}, коротких (<300) {r['deaths']} {r['turns']}")
        print(f"    приборные отказы: {[e for e in r['errs'] if e]}")
        print(f"    городов {r['cities']} (сумма {sum(r['cities'])}), "
              f"макс.размер {r['sizes']}, решения/ход {r['dec']:.2f}")
        print(f"    семьи: {r['fam']}")
    keep, dropped = complete_pairs([base, ban, leg])
    print("=" * 96)
    print(f"годных пар карт (ни одна ветвь не отказала приборно): {len(keep)} из 12; "
          f"исключены игры {[i for i, _ in dropped]}")
    for i, why in dropped:
        print(f"    игра {i} исключена: {why}")
    print("=" * 96)
    verdict(base, ban, "H1 производство полезно (база − запрет)", keep)
    verdict(leg, base, "H3 расширение окупается (прежний путь − база)", keep)