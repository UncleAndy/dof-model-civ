"""Вердикт §10.95 по двум армам: A и B. Метрика — счёт партии (уничтоженный = 0)."""
import json, sys, math
from itertools import combinations

A = sys.argv[1]
B = sys.argv[2]
MIN_DIFF = 2.0      # очков
MIN_FRAC = 0.10     # доля медианы A
ALPHA = 0.05

def load(p):
    out = {}
    for line in open(p):
        try:
            d = json.loads(line)
        except Exception:
            continue
        s = d.get('счёт')
        out[d.get('seed')] = float(s) if isinstance(s, (int, float)) else 0.0
    return out

a, b = load(A), load(B)
seeds = sorted(set(a) & set(b))
print(f"пар скорректировано: {len(seeds)}")
if not seeds:
    raise SystemExit("нет общих сидов")
diffs = [b[s] - a[s] for s in seeds]
med = lambda xs: sorted(xs)[len(xs) // 2]
ma, mb = med([a[s] for s in seeds]), med([b[s] for s in seeds])
print(f"медиана A={ma:.1f}, медиана B={mb:.1f}")
print(f"попарные разности B−A: {[round(d,1) for d in diffs]}")
md = med(diffs)
pos = sum(1 for d in diffs if d > 0)
neg = sum(1 for d in diffs if d < 0)
print(f"медиана разностей={md:.2f}; положительных={pos}, отрицательных={neg}")
# односторонний знаковый тест (биномиальный, H0: p=0.5)
n = pos + neg
from math import comb
p = sum(comb(n, k) for k in range(pos, n + 1)) / (2 ** n) if n else 1.0
print(f"знаковый тест: p={p:.3f} (односторонне, B>A)")
ok = (md >= MIN_DIFF) and (md >= MIN_FRAC * abs(ma) if ma else True) and (p < ALPHA)
print("\nВЕРДИКТ:", "ЭФФЕКТ УСТАНОВЛЕН (§10.111 улучшает)" if ok
      else "эффект НЕ установлен")