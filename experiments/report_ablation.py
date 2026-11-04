#!/usr/bin/env python3
"""Сводка серии абляций: руки против контроля и лестница правил.

    report_ablation.py --series experiments/dof-ab-ablations-6arms
    report_ablation.py --series DIR --metric cities

Печатает три вещи:
  1) средний score на место по рукам (места 0..9, отколовшиеся не в счёте);
  2) парные сравнения с контролем (none) и с full — с кластером по раунду;
  3) внутри игры: DOF-места против классических в каждой руке (проверка, что
     эффект вообще есть и что он растёт по лестнице правил).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stats  # noqa: E402

ORDER = ["none", "ban", "selfdef", "solid", "nowarblock", "full"]  # как в arms.py


def arm_order(arms):
    known = [a for a in ORDER if a in arms]
    return known + [a for a in arms if a not in ORDER]


def arm_mean(rounds, arm, metric):
    vals = [v for row in stats.seat_values(rounds, arm, metric).values() for v in row.values()]
    return (sum(vals) / len(vals)) if vals else None


def inside(rounds, arm, metric):
    """DOF-места против классических внутри одной руки, по раундам."""
    per_round = {}
    for rnd, d in rounds.items():
        sec = (d.get("sections") or {}).get(arm)
        if not sec:
            continue
        roster = sec.get("dof_roster") or ""
        flags = {}
        import re
        for i, f in re.findall(r"idx=(\d+):dof=(\d)", roster):
            flags[int(i)] = int(f)
        dof, cls = [], []
        for n in sec.get("nations") or []:
            if n.get("is_barbarian") or (n.get("id") or 0) >= 10:
                continue
            v = n.get(metric)
            if v is None:
                continue
            (dof if flags.get(int(n["id"])) == 1 else cls).append(v)
        if dof and cls:
            per_round[rnd] = [sum(dof) / len(dof) - sum(cls) / len(cls)]
    return per_round


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--metric", default="score")
    ap.add_argument("--rounds", type=int, default=None, help="взять первые N раундов")
    a = ap.parse_args()

    rounds = stats.load(a.series)
    if not rounds:
        sys.exit("нет раундов")
    if a.rounds:
        rounds = {k: v for k, v in rounds.items() if k < a.rounds}
    arms = arm_order(stats.arms_of(rounds))
    print(f"серия: {a.series}")
    print(f"раундов: {len(rounds)}, метрика: {a.metric}\n")

    print(f"{'рука':12}{'score на место':>16}{'DOF − классика':>18}{'раундов':>9}")
    for arm in arms:
        m = arm_mean(rounds, arm, a.metric)
        ins = inside(rounds, arm, a.metric)
        d = None
        if ins:
            vals = [v for r in ins.values() for v in r]
            d = sum(vals) / len(vals)
        ci = stats.cluster_bootstrap(ins) if ins else None
        tail = f"[{ci[0]:.0f}; {ci[1]:.0f}]" if ci else "—"
        print(f"{arm:12}{(f'{m:.1f}' if m is not None else '—'):>16}"
              f"{(f'{d:+.0f}' if d is not None else '—'):>12} {tail:>10}")

    base = "none" if "none" in arms else arms[0]
    for other in [x for x in arms if x != base]:
        r = stats.describe(rounds, base, other, a.metric)
        if not r:
            continue
        ci = r["ci"]
        ci_txt = f"[{ci[0]:+.0f}; {ci[1]:+.0f}]" if ci else "—"
        print(f"\n{other} − {base}: {r['mean']:+.1f} (медиана {r['median']:+.1f}), "
              f"лучше в {r['wins']}/{r['pairs']}, 95% ДИ по раундам {ci_txt}, "
              f"p(наивно) {r['p_naive']:.2g}")
    if "full" in arms and "ban" in arms:
        r = stats.describe(rounds, "ban", "full", a.metric)
        if r:
            ci = r["ci"]
            ci_txt = f"[{ci[0]:+.0f}; {ci[1]:+.0f}]" if ci else "—"
            print(f"\nfull − ban: {r['mean']:+.1f}, лучше в {r['wins']}/{r['pairs']}, "
                  f"95% ДИ {ci_txt} — это и есть вклад доктрины сверх запрета")


if __name__ == "__main__":
    main()
