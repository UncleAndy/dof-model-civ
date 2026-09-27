#!/usr/bin/env python
"""Два прочтения правила §10.19 — и оба публикуются.

Почему их два. Правило §10.19 п.2 объявляет «ноль решений за матч у ветви ВКЛ»
отказом инструмента и требует такую игру отбросить и повторить. Обоснование в
правиле: «прогноз обязан действовать, если работает». **Измерение это обоснование
опровергло**: в серии 2026-09-27 три игры ветви ВКЛ прошли 50 ходов с нулём решений
при РАБОТАЮЩЕМ прогнозе — он 50 раз подряд отказал с причиной «нет строгого
улучшения (кандидаты: move 4)»: под носителем нет годной площадки, а цена раскрытия
(разрыв Дженсена) на этих картах равна нулю, поэтому все кандидаты имеют ровно
нулевую дельту. Это исход политики, тот же нулевой застой, что документирован для
прежнего пути (§5.2i навыка).

Асимметрия опасна: если у ВКЛ застой отбрасывать, а у ВЫКЛ (где он тоже бывает)
нет — сравнение сместится в пользу ВКЛ, ведь застойная игра приносит счёт 0.
Поэтому считаются ОБА прочтения и публикуются оба, а не выбирается удобное:

  A. буквальное правило §10.19 (у ВКЛ ноль действий — отброс, у ВЫКЛ — нет);
  B. симметричное (у обеих ветвей отбрасываются только error/клин/min_entities==0/
     0 ходов; застойные игры остаются как ИСХОД политики).

Вердикт в обоих случаях — правило §10.19 п.5: интервал разницы без нуля И
положительная медиана разницы.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ab_two_arm_verdict import (  # noqa: E402
    REQUIRED_CLEAN,
    arm_stats,
    bootstrap_diff_ci,
    load_rows,
    rejection_reason,
)


def strict_reasons(row: dict, arm: str) -> str | None:
    """Только отказы инструмента, одинаковые для обеих ветвей."""
    if str(row.get("error") or "").strip():
        return f"error: {row['error']}"
    if row.get("wedge_action"):
        return f"клин: {row['wedge_action']}"
    if row.get("min_entities") == 0:
        return "min_entities == 0 (стенд не отдал мир)"
    if int(row.get("turns") or 0) <= 0:
        return "0 ходов"
    return None


def split(rows, fn, arm):
    clean, dropped = [], []
    for row in rows:
        reason = fn(row, arm)
        if reason is None:
            clean.append(row)
        else:
            dropped.append(reason)
    return clean, dropped


def verdict_line(name: str, on_rows, off_rows) -> None:
    on_scores = [float(r.get("score_cum") or 0.0) for r in on_rows]
    off_scores = [float(r.get("score_cum") or 0.0) for r in off_rows]
    print(f"\n--- {name}")
    if len(on_scores) < REQUIRED_CLEAN or len(off_scores) < REQUIRED_CLEAN:
        print(f"  недобор: чистых ВКЛ {len(on_scores)}, ВЫКЛ {len(off_scores)} "
              f"(нужно {REQUIRED_CLEAN} на ветвь) — вердикта нет")
        return
    low, high = bootstrap_diff_ci(on_scores, off_scores)
    pair = [a - b for a, b in zip(on_scores[:len(off_scores)],
                                 off_scores[:len(on_scores)])]
    diff_mean = statistics.fmean(on_scores) - statistics.fmean(off_scores)
    diff_median = statistics.median(pair) if pair else 0.0
    print(f"  ВКЛ: n={len(on_scores)} среднее={statistics.fmean(on_scores):.2f} "
          f"медиана={statistics.median(on_scores):.2f}")
    print(f"  ВЫКЛ: n={len(off_scores)} среднее={statistics.fmean(off_scores):.2f} "
          f"медиана={statistics.median(off_scores):.2f}")
    print(f"  разница средних (непарная): {diff_mean:+.2f}, 95% CI "
          f"[{low:+.2f}, {high:+.2f}]; медиана попарной разницы {diff_median:+.2f}")
    if low > 0.0 or high < 0.0:
        side = "ВКЛ" if low > 0.0 else "ВЫКЛ"
        print(f"  ВЕРДИКТ: различие есть, в пользу {side} (интервал не содержит нуля)")
    else:
        print("  ВЕРДИКТ: различия не показано (интервал содержит нуль) — "
              "это полноценный результат")


def freeze_stats(rows):
    zero = [r for r in rows if int(r.get("actions_issued") or 0) <= 0]
    return len(zero), len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--on", nargs="+", required=True)
    parser.add_argument("--off", nargs="+", required=True)
    args = parser.parse_args()

    on_rows, on_problems = load_rows(args.on)
    off_rows, off_problems = load_rows(args.off)
    for problem in on_problems + off_problems:
        print(f"ВНИМАНИЕ: {problem}")

    print(f"всего записей: ВКЛ {len(on_rows)}, ВЫКЛ {len(off_rows)}")
    for name, rows in (("ВКЛ", on_rows), ("ВЫКЛ", off_rows)):
        frozen, total = freeze_stats(rows)
        print(f"  {name}: застойных игр (0 действий) {frozen} из {total}"
              f" = {100.0 * frozen / total if total else 0.0:.0f}%")
        stats = arm_stats(rows)
        print(f"       действий/ход {stats.get('actions_per_turn', 0):.2f}, "
              f"пропущенных ходов {stats.get('skipped_turns', 0)}")

    # A. буквальное правило
    a_on, a_on_drop = split(on_rows, rejection_reason, "on")
    a_off, a_off_drop = split(off_rows, rejection_reason, "off")
    print(f"\n=== A. БУКВАЛЬНОЕ правило §10.19")
    print(f"  отброшено ВКЛ: {len(a_on_drop)} {a_on_drop}")
    print(f"  отброшено ВЫКЛ: {len(a_off_drop)} {a_off_drop}")
    verdict_line("A", a_on, a_off)

    # B. симметричное
    b_on, b_on_drop = split(on_rows, strict_reasons, "on")
    b_off, b_off_drop = split(off_rows, strict_reasons, "off")
    print(f"\n=== B. СИММЕТРИЧНОЕ прочтение (застой — исход политики)")
    print(f"  отброшено ВКЛ: {len(b_on_drop)} {b_on_drop}")
    print(f"  отброшено ВЫКЛ: {len(b_off_drop)} {b_off_drop}")
    verdict_line("B", b_on, b_off)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
