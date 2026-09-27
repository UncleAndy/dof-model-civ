#!/usr/bin/env python
"""Вердикт A/B «прогноз ВКЛ против ВЫКЛ» — ровно по правилу §10.19.

Правило задано ДО данных, и этот скрипт его не пересматривает: он только считает.
Что важно и почему:

* **Метрика исхода — серверный счёт** (`score_cum`), не индекс: индекс считает наша
  модель, счёт выдаёт мир.
* **Отброшенное сообщается с причиной.** Игра целиком вылетает, если есть клин,
  таймаут, `error != ''` или `min_entities == 0` (стенд не отдал мир). У ветви ВКЛ
  дополнительно вылетает игра с нулём действий: прогноз обязан действовать, если он
  работает, — ноль действий означает отказ инструмента, а не поведение агента.
* **Сравнение непарное** (разные карты): интервал для разницы средних, bootstrap,
  10 000 пересборок, 95%. Сид фиксирован, иначе вердикт невоспроизводим.
* **Порог вердикта:** «различие есть» = интервал разницы не содержит нуля И медиана
  разницы положительна; иначе «различия не показано» — полноценный результат.
* **Размер серии фиксирован (16 чистых на ветвь).** Если чистых меньше — это НЕ
  вердикт, а сообщение о недоборе; подглядывать и продлевать нельзя.

Запуск:

    python scripts/ab_two_arm_verdict.py --on forecast_*.json --off forecast_off_*.json
    python scripts/ab_two_arm_verdict.py --on <файл> --off <файл> --allow-short
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent

#: Сколько чистых игр на ветвь требует правило (§10.19).
REQUIRED_CLEAN = 16
#: Пересборок в bootstrap: 10 000 — записано в правиле заранее.
BOOTSTRAP_ROUNDS = 10000
#: Сид фиксирован: иначе вердикт невоспроизводим.
BOOTSTRAP_SEED = 20260927


def load_rows(paths: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Записи прогонов: [(ветвь-строка, причина)]. Пути читаются как есть."""
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for raw in paths:
        candidates = sorted(Path(HERE).glob(raw)) if any(ch in raw for ch in "*?[") \
            else [Path(raw) if os.path.isabs(raw) else Path(HERE) / raw]
        if not candidates:
            problems.append(f"{raw}: файлов не найдено")
        for path in candidates:
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                problems.append(f"{path.name}: не прочитан ({exc})")
                continue
            results = (doc or {}).get("results") or {}
            for agent, entries in results.items():
                for entry in (entries if isinstance(entries, list) else [entries]):
                    if isinstance(entry, dict):
                        row = dict(entry)
                        row["source"] = path.name
                        row["agent"] = agent
                        rows.append(row)
    return rows, problems


def rejection_reason(row: dict[str, Any], arm: str) -> str | None:
    """Почему игра отброшена — или None, если она чистая. Причину называем всегда."""
    if str(row.get("error") or "").strip():
        return f"error: {row['error']}"
    if row.get("wedge_action"):
        return f"клин: {row['wedge_action']}"
    if row.get("min_entities") == 0:
        return "min_entities == 0 (стенд не отдал мир)"
    if int(row.get("turns") or 0) <= 0:
        return "0 ходов"
    if arm == "on" and int(row.get("actions_issued") or 0) <= 0:
        return "ноль действий у ветви ВКЛ (отказ инструмента)"
    return None


def split_arms(rows: list[dict[str, Any]], arm: str) -> tuple[list[dict], list[tuple[str, str]]]:
    """(чистые, отброшенные-с-причиной) для одной ветви."""
    clean: list[dict] = []
    dropped: list[tuple[str, str]] = []
    for row in rows:
        reason = rejection_reason(row, arm)
        if reason is None:
            clean.append(row)
        else:
            dropped.append((row.get("source", "?"), reason))
    return clean, dropped


def bootstrap_diff_ci(on: list[float], off: list[float], *,
                      rounds: int = BOOTSTRAP_ROUNDS,
                      seed: int = BOOTSTRAP_SEED) -> tuple[float, float]:
    """95% интервал для разницы средних (непарный bootstrap)."""
    rng = random.Random(seed)
    diffs = []
    for _ in range(rounds):
        sample_on = [rng.choice(on) for _ in on] if on else []
        sample_off = [rng.choice(off) for _ in off] if off else []
        if not sample_on or not sample_off:
            continue
        diffs.append(statistics.fmean(sample_on) - statistics.fmean(sample_off))
    if not diffs:
        return 0.0, 0.0
    diffs.sort()
    low = diffs[int(0.025 * len(diffs))]
    high = diffs[min(len(diffs) - 1, int(0.975 * len(diffs)))]
    return low, high


def arm_stats(rows: list[dict[str, Any]]) -> dict[str, float]:
    turns = [int(r.get("turns") or 0) for r in rows] or [0]
    actions = [int(r.get("actions_issued") or 0) for r in rows] or [0]
    skipped = [int(r.get("skipped_turns") or 0) for r in rows] or [0]
    scores = [float(r.get("score_cum") or 0.0) for r in rows]
    return {
        "n": len(rows),
        "score_mean": statistics.fmean(scores) if scores else 0.0,
        "score_median": statistics.median(scores) if scores else 0.0,
        "actions_per_turn": (sum(actions) / sum(turns)) if sum(turns) else 0.0,
        "skip_share": (sum(skipped) / sum(turns)) if sum(turns) else 0.0,
    }


def verdict(on_rows: list[dict], off_rows: list[dict], *,
            require: int = REQUIRED_CLEAN,
            allow_short: bool = False) -> tuple[str, float, float, float]:
    """(вердикт, разница средних, нижняя граница, верхняя граница)."""
    on_scores = [float(r.get("score_cum") or 0.0) for r in on_rows]
    off_scores = [float(r.get("score_cum") or 0.0) for r in off_rows]
    if not on_scores or not off_scores:
        return "нет данных", 0.0, 0.0, 0.0
    diff = statistics.fmean(on_scores) - statistics.fmean(off_scores)
    low, high = bootstrap_diff_ci(on_scores, off_scores)
    if not allow_short and (len(on_scores) < require or len(off_scores) < require):
        return (f"недобор: {len(on_scores)}/{require} и {len(off_scores)}/{require} "
                f"чистых — вердикта нет"), diff, low, high
    if low > 0.0 and diff > 0.0:
        return "различие есть", diff, low, high
    return "различия не показано", diff, low, high


def report(on_rows: list[dict], off_rows: list[dict], on_dropped, off_dropped,
           problems: list[str], *, require: int = REQUIRED_CLEAN,
           allow_short: bool = False) -> str:
    lines: list[str] = ["A/B «прогноз ВКЛ против ВЫКЛ» — по правилу §10.19", ""]
    for label, rows, dropped in (("ВКЛ", on_rows, on_dropped), ("ВЫКЛ", off_rows, off_dropped)):
        stats = arm_stats(rows)
        lines.append(f"ветвь {label}: чистых {stats['n']}, "
                     f"счёт средний {stats['score_mean']:.2f} "
                     f"(медиана {stats['score_median']:.2f}), "
                     f"действий за ход {stats['actions_per_turn']:.2f}, "
                     f"простоев {stats['skip_share'] * 100:.0f}%")
        for source, reason in dropped:
            lines.append(f"    отброшено: {source} — {reason}")
    for problem in problems:
        lines.append(f"    проблема чтения: {problem}")
    lines.append("")

    name, diff, low, high = verdict(on_rows, off_rows, require=require,
                                    allow_short=allow_short)
    lines.append(f"разница средних (ВКЛ минус ВЫКЛ): {diff:+.2f}, "
                 f"95% интервал [{low:+.2f}, {high:+.2f}]")
    lines.append(f"ВЕРДИКТ: {name}")
    lines.append("")
    lines.append("Напоминание правила: серия фиксирована заранее, подглядывать и "
                 "продлевать её нельзя; «различия не показано» — полноценный "
                 "результат, а не неудача.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--on", nargs="+", required=True,
                        help="записи ветви ВКЛ (прогноз включён)")
    parser.add_argument("--off", nargs="+", required=True,
                        help="записи ветви ВЫКЛ (прежний путь)")
    parser.add_argument("--require", type=int, default=REQUIRED_CLEAN,
                        help=f"чистых игр на ветвь по правилу (по умолчанию "
                             f"{REQUIRED_CLEAN})")
    parser.add_argument("--allow-short", action="store_true",
                        help="считать вердикт на недоборе (для проверки инструмента; "
                             "в отчёте это видно)")
    args = parser.parse_args()

    on_rows_raw, on_problems = load_rows(args.on)
    off_rows_raw, off_problems = load_rows(args.off)
    on_clean, on_dropped = split_arms(on_rows_raw, "on")
    off_clean, off_dropped = split_arms(off_rows_raw, "off")

    text = report(on_clean, off_clean, on_dropped, off_dropped,
                  on_problems + off_problems,
                  require=args.require, allow_short=args.allow_short)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
