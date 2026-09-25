"""
Statistics helpers for tournament reporting.

Deliberately dependency-free (stdlib only): the project runs inside a Nix venv
where scipy is not guaranteed, and the analysis must be reproducible from the
raw per-episode records.

Two things are provided:

* ``ci95`` — Student-t 95% confidence interval for a mean. With the episode
  counts we actually run (tens), the normal approximation is too optimistic,
  so a t table is used.
* ``bootstrap_diff_ci`` — non-parametric 95% CI for the difference of two
  means (percentile bootstrap). Used for agent-vs-baseline comparisons, where
  normality of the DoF metric cannot be assumed.
"""
from __future__ import annotations

import math
import random

# Two-sided 95% t critical values by degrees of freedom.
_T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
    40: 2.021, 50: 2.009, 60: 2.000, 80: 1.990, 100: 1.984,
    120: 1.980,
}
_Z95 = 1.960  # large-sample limit


def t_critical_95(df: int) -> float:
    """Two-sided 95% t critical value for ``df`` degrees of freedom."""
    if df <= 0:
        return float("inf")
    if df in _T95:
        return _T95[df]
    if df > 120:
        return _Z95
    # nearest tabulated df, conservative direction (smaller df -> larger t)
    smaller = max((k for k in _T95 if k < df), default=None)
    if smaller is not None:
        return _T95[smaller]
    return _Z95


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: list[float]) -> float:
    """Sample standard deviation (n-1). 0.0 for n < 2."""
    n = len(values)
    if n < 2:
        return 0.0
    mu = mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def sem(values: list[float]) -> float:
    """Standard error of the mean."""
    n = len(values)
    if n < 2:
        return 0.0
    return stdev(values) / math.sqrt(n)


def ci95(values: list[float]) -> tuple[float, float]:
    """Student-t 95% CI for the mean. Degenerate (v, v) for n < 2."""
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    mu = mean(values)
    if n < 2:
        return (mu, mu)
    half = t_critical_95(n - 1) * sem(values)
    return (mu - half, mu + half)


def bootstrap_diff_ci(
    a: list[float],
    b: list[float],
    n_resamples: int = 10000,
    seed: int = 12345,
) -> tuple[float, float, float]:
    """Percentile-bootstrap 95% CI for ``mean(a) - mean(b)``.

    Returns ``(lo, hi, point)``. A CI that excludes 0 is evidence of a real
    difference at the ~5% level without assuming normality.
    """
    if not a or not b:
        return (0.0, 0.0, 0.0)

    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(n_resamples):
        ra = [a[rng.randrange(len(a))] for _ in range(len(a))]
        rb = [b[rng.randrange(len(b))] for _ in range(len(b))]
        diffs.append(mean(ra) - mean(rb))

    diffs.sort()
    lo = diffs[int(0.025 * n_resamples)]
    hi = diffs[int(0.975 * n_resamples) - 1]
    return (lo, hi, mean(a) - mean(b))


def cohens_d(a: list[float], b: list[float]) -> float:
    """Standardised mean difference (pooled SD). 0.0 when undefined."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0
    sa, sb = stdev(a), stdev(b)
    pooled = math.sqrt(((na - 1) * sa**2 + (nb - 1) * sb**2) / (na + nb - 2))
    if pooled == 0:
        return 0.0
    return (mean(a) - mean(b)) / pooled