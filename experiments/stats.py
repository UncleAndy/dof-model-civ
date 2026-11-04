#!/usr/bin/env python3
"""Парные сравнения рук с кластером по раунду.

Зачем: все руки раунда играют одну карту, поэтому пары «(раунд, место)» внутри
раунда зависимы. Парный t-тест по 1000 парам считает их независимыми и завышает
точность; здесь неопределённость оценивается бутстрапом по РАУНДАМ (кластер =
одна карта), а t-тест печатается рядом для контраста.

    stats.py --series experiments/dof-ab-ablations-6arms --arms full,ban --metric score
    stats.py --series DIR --list                 # какие руки есть в данных
    stats.py --series DIR --arms all --metric score   # каждая рука против контроля
"""
import argparse
import glob
import json
import math
import os
import random
import statistics as st
import sys

METRICS = ("score", "cities", "population_real", "techs", "bulbs_last_turn",
           "units_killed", "units_lost", "gold", "landarea")


def load(path):
    rounds = {}
    for f in sorted(glob.glob(os.path.join(path, "rounds", "round_*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        rounds[d["round"]] = d
    return rounds


def arms_of(rounds):
    names = set()
    for d in rounds.values():
        names |= set(d.get("sections") or {})
    return sorted(names)


def seat_values(rounds, arm, metric):
    """{раунд: {место: значение}} — только места 0..9, только живые значения."""
    out = {}
    for rnd, d in rounds.items():
        sec = (d.get("sections") or {}).get(arm)
        if not sec:
            continue
        row = {}
        for n in sec.get("nations") or []:
            if n.get("is_barbarian") or (n.get("id") or 0) >= 10:
                continue
            v = n.get(metric)
            if v is None:
                continue
            row[int(n["id"])] = v
        out[rnd] = row
    return out


def paired(rounds, a, b, metric):
    """Разности b − a по каждой паре (раунд, место), сгруппированные по раунду."""
    va, vb = seat_values(rounds, a, metric), seat_values(rounds, b, metric)
    by_round = {}
    for rnd in sorted(set(va) & set(vb)):
        diffs = [vb[rnd][s] - va[rnd][s] for s in sorted(set(va[rnd]) & set(vb[rnd]))]
        if diffs:
            by_round[rnd] = diffs
    return by_round


def cluster_bootstrap(by_round, B=4000, seed=20261104):
    """ДИ среднего эффекта при ресемплинге РАУНДОВ (карт), а не пар."""
    rnds = sorted(by_round)
    if len(rnds) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(B):
        pick = [rng.choice(rnds) for _ in rnds]
        vals = [v for r in pick for v in by_round[r]]
        means.append(sum(vals) / len(vals))
    means.sort()
    lo = means[int(0.025 * B)]
    hi = means[int(0.975 * B) - 1]
    return lo, hi


def naive_t(by_round):
    """Парный t по всем парам без кластера — для контраста, не для вывода."""
    vals = [v for r in sorted(by_round) for v in by_round[r]]
    n = len(vals)
    if n < 3:
        return None, None
    m = sum(vals) / n
    sd = st.stdev(vals)
    if sd == 0:
        return m, 1.0
    t = m / (sd / math.sqrt(n))
    # двусторонний p по нормальному приближению (n велико)
    p = math.erfc(abs(t) / math.sqrt(2))
    return m, p


def describe(rounds, a, b, metric):
    by_round = paired(rounds, a, b, metric)
    if not by_round:
        return None
    vals = [v for r in sorted(by_round) for v in by_round[r]]
    mean = sum(vals) / len(vals)
    wins = sum(1 for v in vals if v > 0)
    ci = cluster_bootstrap(by_round)
    _, p = naive_t(by_round)
    return {"pairs": len(vals), "rounds": len(by_round), "mean": mean,
            "median": st.median(vals), "wins": wins, "ci": ci, "p_naive": p}


def fmt(x, w=9, nd=1):
    if x is None:
        return "—".rjust(w)
    return f"{x:>{w}.{nd}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--arms", default="", help="'full,ban' или 'all' (каждая против первой)")
    ap.add_argument("--metric", default="score", choices=METRICS + ("all",))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    rounds = load(a.series)
    if not rounds:
        sys.exit(f"в {a.series} нет раундов")
    arms = arms_of(rounds)
    if a.list or not a.arms:
        print(f"раундов {len(rounds)}, руки: {', '.join(arms)}")
        for arm in arms:
            vals = [v for row in seat_values(rounds, arm, "score").values() for v in row.values()]
            print(f"  {arm:12} мест {len(vals):5}  score на место {fmt(sum(vals)/len(vals) if vals else None, 8)}")
        return

    names = [x.strip() for x in a.arms.split(",") if x.strip()]
    pairs = []
    if names == ["all"]:
        base = arms[0] if "none" not in arms else "none"
        pairs = [(base, x) for x in arms if x != base]
    elif len(names) == 2:
        pairs = [(names[0], names[1])]
    else:
        sys.exit("--arms: два имени через запятую или 'all'")

    metrics = METRICS if a.metric == "all" else (a.metric,)
    for base, other in pairs:
        print(f"\n{other} − {base}  (плюс = лучше {other})")
        print(f"{'метрика':16}{'пар':>6}{'раундов':>8}{'среднее':>10}{'медиана':>10}"
              f"{'лучше':>8}{'95% ДИ (кластер)':>22}{'p (наивно)':>12}")
        for m in metrics:
            r = describe(rounds, base, other, m)
            if not r:
                continue
            ci = ("[%s; %s]" % (fmt(r["ci"][0], 8), fmt(r["ci"][1], 8))) if r["ci"] else "—"
            print(f"{m:16}{r['pairs']:6}{r['rounds']:8}{fmt(r['mean'], 10)}{fmt(r['median'], 10)}"
                  f"{r['wins']:8}{ci:>22}{fmt(r['p_naive'], 12, 3)}")


if __name__ == "__main__":
    main()
