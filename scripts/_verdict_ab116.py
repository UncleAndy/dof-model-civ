"""Вердикт A/B §10.116 по правилу §10.95/§10.104.

Читает knowledge/results_ab116_A.jsonl и _B.jsonl, сопоставляет по сиду и считает:
  - медиану попарных разностей (A − B);
  - односторонний знаковый тест (p по биномиальному распределению, H1: A > B);
  - относительный порог (медиана разностей ≥ 10% медианы |B|, снимается при медиане B = 0).
Печатает таблицу и вердикт. Порогов НЕ подбирает — они объявлены в протоколе.
"""
from __future__ import annotations

import json
import statistics
import sys
from math import comb


def load(path: str) -> dict:
    out = {}
    try:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            out[int(r["seed"])] = r
    except FileNotFoundError:
        pass
    return out


A = load(sys.argv[1] if len(sys.argv) > 1 else "knowledge/results_ab116_A.jsonl")
B = load(sys.argv[2] if len(sys.argv) > 2 else "knowledge/results_ab116_B.jsonl")
seeds = sorted(set(A) & set(B))
if not seeds:
    print("нет общих сидов — серия не закончена?")
    sys.exit(1)


def score(r: dict) -> float:
    s = r.get("счёт")
    return 0.0 if s is None else float(s)


print(f"{'сид':>6s} {'A':>5s} {'B':>5s} {'A−B':>6s}   A_гор B_гор")
diffs = []
for s in seeds:
    a, b = score(A[s]), score(B[s])
    diffs.append(a - b)
    print(f"{s:>6d} {a:>5.0f} {b:>5.0f} {a-b:>+6.0f}   {A[s].get('городов')} {B[s].get('городов')}")

n = len(diffs)
pos = sum(1 for d in diffs if d > 0)
neg = sum(1 for d in diffs if d < 0)
zero = sum(1 for d in diffs if d == 0)
med = statistics.median(diffs)
medB = statistics.median([abs(score(B[s])) for s in seeds])

# односторонний знаковый тест: H1 A > B; игнорируем нули (n_eff), p = P(X ≥ pos | p=0.5)
n_eff = pos + neg
p = sum(comb(n_eff, k) for k in range(pos, n_eff + 1)) / (2 ** n_eff) if n_eff else 1.0

print(f"\nn пар = {n}; положительных {pos}, отрицательных {neg}, нулей {zero}")
print(f"медиана разностей (A−B) = {med:+.2f}")
print(f"медиана |B| = {medB:.2f}; 10% порог = {0.1*medB:.2f}")
print(f"знаковый тест: n_eff={n_eff}, p = {p:.4f}")

ok1 = med >= 2
ok2 = p < 0.05
ok3 = (medB == 0) or (med >= 0.1 * medB)
print("\nКРИТЕРИЙ §10.95:")
print(f"  медиана ≥ 2 очка:              {'ДА' if ok1 else 'НЕТ'} ({med:+.2f})")
print(f"  знаковый тест p < 0.05:        {'ДА' if ok2 else 'НЕТ'} (p={p:.4f})")
print(f"  медиана ≥ 10% медианы |B|:     {'—(снят)' if medB == 0 else ('ДА' if ok3 else 'НЕТ')}")
print("\nВЕРДИКТ:", "ЭФФЕКТ УСТАНОВЛЕН" if (ok1 and ok2 and ok3) else "ЭФФЕКТ НЕ УСТАНОВЛЕН")
