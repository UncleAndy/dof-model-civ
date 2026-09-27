#!/usr/bin/env python3
"""Цена глубины планирования: сколько миллисекунд стоит одно решение.

Нужно, чтобы обсуждать горизонт числами, а не ощущениями. Стоимость поиска
растёт как «кандидаты в степени горизонт», поэтому измеряем на реальных размерах
состояния из живых матчей: около 95 сущностей и 6–12 кандидатов на решение
(в замерзших матчах наблюдалось ровно 6).

    python scripts/bench_lookahead.py --horizons 3,4,5,6,7 --candidates 6,8,12
"""
from __future__ import annotations

import argparse
import time

from dof_core import CoreAction, CoreEntity, DOFCalculusCore


def make_case(n_candidates: int, n_entities: int = 95):
    """Состояние и кандидаты в масштабе ядра (доли, кламп 1.0 — как в бою)."""
    ents = [CoreEntity(entity_id=f"unit_{i}", current_dof=0.5,
                       is_reversible=True) for i in range(n_entities - 1)]
    ents.append(CoreEntity(entity_id="city_1", current_dof=0.8, is_reversible=False))
    acts = []
    for i in range(n_candidates):
        # Кандидат трогает свою сущность: дельта заметно меньше шкалы ядра,
        # иначе кламп 1.0 срежет разницу и замер станет оптимистичным.
        acts.append(CoreAction(action_id=f"cand_{i}", description="",
                               dof_delta=[(f"unit_{i}", 0.01)],
                               is_reversible=(i % 3 != 0)))
    return ents, acts


def time_case(n_candidates: int, horizon: int, repeats: int = 3) -> float:
    ents, acts = make_case(n_candidates)
    core = DOFCalculusCore(lookahead_horizon=horizon, context_switch_penalty=0.05)
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        core.select_best(ents, acts)
        best = min(best, time.perf_counter() - t0)
    return best * 1000.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", default="3,4,5,6,7")
    ap.add_argument("--candidates", default="6,8,12")
    ap.add_argument("--decisions-per-match", type=float, default=45.0,
                    help="сколько решений в матче 50 ходов при наблюдённых 0.9/ход")
    args = ap.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    cands = [int(c) for c in args.candidates.split(",")]

    print("=" * 78)
    print("ЦЕНА ГОРИЗОНТА ПЛАНИРОВАНИЯ (состояние ~95 сущностей, лучшее из 3 прогонов)")
    print("=" * 78)
    head = f"{'кандидатов':>11}" + "".join(f"{f'H={h}':>16}" for h in horizons)
    print(head)
    print("-" * len(head))
    for c in cands:
        row = f"{c:>11}"
        for h in horizons:
            try:
                ms = time_case(c, h)
                row += f"{ms:>13.1f} мс"
            except Exception as exc:  # noqa: BLE001
                row += f"{'ошибка: ' + type(exc).__name__:>16}"
        print(row)
    print()
    print("На матч (50 ходов) при %d решениях:" % int(args.decisions_per_match))
    for c in cands:
        per = []
        for h in horizons:
            try:
                ms = time_case(c, h, repeats=1)
                per.append(f"H={h}: {ms * args.decisions_per_match / 1000:.1f} с")
            except Exception:  # noqa: BLE001
                per.append(f"H={h}: —")
        print(f"  кандидатов {c:>3}: " + "   ".join(per))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
