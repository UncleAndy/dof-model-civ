#!/usr/bin/env python
"""Траектория по горизонтам: где именно расходятся ветви.

Описание, а не вердикт: вердикт §10.23 ставится только на 150 ходах. Здесь по
сохранённым рядам счёта считается накопленный счёт к 10/30/50/100/150 ходам для
каждой игры, достигшей горизонта, и разница средних по ветвям. Игра попадает в
горизонт только если реально до него дошла (то же правило, что в серии любопытства).
"""
from __future__ import annotations

import argparse
import json
import statistics

HORIZONS = (10, 30, 50, 100, 150)


def load(paths):
    rows = []
    for path in paths:
        doc = json.load(open(path, encoding="utf-8"))
        for agent, entries in ((doc.get("results") or {})).items():
            for entry in (entries if isinstance(entries, list) else [entries]):
                if isinstance(entry, dict):
                    rows.append(entry)
    return rows


def cumulative_at(row, horizon):
    """Накопленный счёт к горизонту: сумма надбавок, случившихся не позже него.

    Ряд счёта РАЗРЕЖЁН (`score_series` = [{'turn': T, 'delta': D}, …], только
    изменения), поэтому «к 30 ходам» — это сумма дельт с turn ≤ 30, а не сумма
    первых 30 элементов. Игра учитывается на горизонте только если до него дошла.
    """
    turns = row.get("turns_series") or []
    if turns and len(turns) < horizon:
        return None
    if not turns and int(row.get("turns") or 0) < horizon:
        return None
    total = 0.0
    for item in row.get("score_series") or []:
        if isinstance(item, dict):
            try:
                if float(item.get("turn") or 0) <= horizon:
                    total += float(item.get("delta") or 0.0)
            except (TypeError, ValueError):
                continue
        else:
            return None
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--on", nargs="+", required=True)
    parser.add_argument("--off", nargs="+", required=True)
    args = parser.parse_args()
    on_rows = load(args.on)
    off_rows = load(args.off)
    print(f"{'горизонт':>9} {'ВКЛ n':>6} {'среднее ВКЛ':>12} {'ВЫКЛ n':>6} "
          f"{'среднее ВЫКЛ':>12} {'разница':>9}")
    for horizon in HORIZONS:
        on = [v for v in (cumulative_at(r, horizon) for r in on_rows) if v is not None]
        off = [v for v in (cumulative_at(r, horizon) for r in off_rows) if v is not None]
        if not on or not off:
            print(f"{horizon:>9} {len(on):>6} {'—':>12} {len(off):>6} {'—':>12} {'—':>9}")
            continue
        diff = statistics.fmean(on) - statistics.fmean(off)
        print(f"{horizon:>9} {len(on):>6} {statistics.fmean(on):>12.2f} "
              f"{len(off):>6} {statistics.fmean(off):>12.2f} {diff:>+9.2f}")
    print("\n(накопленный серверный счёт к горизонту; игра учитывается, только если "
          "дошла до него — иначе ряд короче и горизонт не приписывается)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
