#!/usr/bin/env python
"""Сверка воспроизводимости: круг 1 (до перезагрузки стенда) против круга 2.

Сравниваются: счёт по играм (медиана, разброс, сумма), вердикт по правилу §10.44
для каждой ветви и его устойчивость между кругами.
"""
import json
import random
import statistics


def load(path):
    d = json.load(open(path))
    eps = list(d["results"].values())[0]
    return [float(e.get("score_cum") or 0) for e in eps]


def boot_diff(a, b, n=20000, seed=7):
    rnd = random.Random(seed)
    diffs = []
    for _ in range(n):
        da = [rnd.choice(a) for _ in a]
        db = [rnd.choice(b) for _ in b]
        diffs.append(statistics.median(da) - statistics.median(db))
    diffs.sort()
    return diffs[int(0.025 * n)], diffs[int(0.975 * n)]


ARMS = ("base", "ban", "legacy")
r1 = {a: load(f"/tmp/h150n12r1_h150n12_{a}.json") for a in ARMS}
r2 = {a: load(f"/tmp/h150n12_{a}.json") for a in ARMS}

print("=" * 96)
for a in ARMS:
    for tag, r in (("круг 1", r1[a]), ("круг 2", r2[a])):
        s = sorted(r)
        print(f"{a:7s} {tag}: медиана {statistics.median(r):5.1f}  разброс "
              f"{min(r):4.0f}..{max(r):4.0f}  сумма {sum(r):5.0f}  игры {[round(x) for x in r]}")
    lo, hi = boot_diff(r2[a], r1[a])
    print(f"        сдвиг круг2 − круг1: медианы "
          f"{statistics.median(r2[a]) - statistics.median(r1[a]):+.1f}, "
          f"CI [{lo:+.1f}, {hi:+.1f}] -> "
          f"{'воспроизводится' if lo <= 0 <= hi else 'РАСХОЖДЕНИЕ'}")
    print()

print("=" * 96)
print("Вердикт по правилу §10.44 в каждом круге:")
for circle, r in (("круг 1", r1), ("круг 2", r2)):
    mb, mn, ml = (statistics.median(r[a]) for a in ("base", "ban", "legacy"))
    lo1, hi1 = boot_diff(r["base"], r["ban"])
    lo3, hi3 = boot_diff(r["legacy"], r["base"])
    v1 = "H1 подтверждена" if (mb >= mn + 2 and lo1 > 0) else (
        "H2 подтверждена" if (mn >= mb + 2 and hi1 < 0) else "H1 не установлена")
    v3 = "H3 подтверждена" if (ml >= mb + 2 and lo3 > 0) else "H3 не установлена"
    print(f"  {circle}: медианы база {mb:.1f} / запрет {mn:.1f} / прежний {ml:.1f}; "
          f"{v1}, {v3}")