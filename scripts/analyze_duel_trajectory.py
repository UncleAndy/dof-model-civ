#!/usr/bin/env python3
"""Траектория счёта в дуэли: не только «кто больше в конце», но «когда».

Зачем. Счёт игры грубый и редкий (целые малые величины; контрольные точки раз в
150 ходов), поэтому различие в поведении может не успеть стать различием в
итоговом счёте за короткий матч. Тогда содержателен только вопрос: **на каком
ходу** варианты начали расходиться и расходились ли вообще.

Как считается. У каждой стороны матча есть своя траектория — дельты счёта по
ходам (серверный сигнал, `score_series` в метриках). Для каждого горизонта
считаем накопленный счёт X и Y и их разницу; вердикт по каждому горизонту — тот
же предзарегистрированный (`ab_verdict`), поэтому «на 25-м ходу различия ещё
нет, а на 50-м есть» — это результат, а не подгонка.

Записи берутся те же, что писал прогон: `/tmp/duel_<игра>_<сторона>.json`, а
сторона варианта X восстанавливается по схеме прогона (чётные игры — X играл за
B, потому что стороны переставляются).

    python scripts/analyze_duel_trajectory.py --games 6 --horizons 10,20,30,40,50
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metrics.duel import ab_verdict, cumulative  # noqa: E402
from baselines.run_duel import _dead_side  # noqa: E402


def load_side(path: Path) -> dict | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    for _agent, records in (payload.get("results") or {}).items():
        for rec in records:
            return rec
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--games", type=int, default=6,
                   help="сколько игр было в прогоне (нумерация совпадает с логами)")
    p.add_argument("--pattern", default="/tmp/duel_{game}_{side}.json")
    p.add_argument("--horizons", default="10,20,30,40,50")
    p.add_argument("--min-games", type=int, default=3)
    p.add_argument("--swap", dest="swap", action="store_true", default=True,
                   help="стороны переставлялись между играми (чётные игры: X за B)")
    p.add_argument("--no-swap", dest="swap", action="store_false")
    args = p.parse_args()

    horizons = [int(h) for h in args.horizons.split(",") if h.strip()]
    games = []
    dead = []
    for g in range(1, args.games + 1):
        a = load_side(Path(args.pattern.format(game=g, side="a")))
        b = load_side(Path(args.pattern.format(game=g, side="b")))
        if not a or not b:
            continue
        x_side = "b" if (args.swap and g % 2 == 0) else "a"
        xr, yr = (a, b) if x_side == "a" else (b, a)
        if _dead_side(xr) or _dead_side(yr):
            # Сторона не сделала ни одного решения — отказ инструмента, а не
            # политика. Тот же фильтр, что в оркестраторе: правило обязано быть
            # одно, иначе траектория «доказывает» разницу, которой в игре не было.
            dead.append(g)
            continue
        games.append({"game": g, "x": xr, "y": yr,
                      "x_turns": float(xr.get("turns") or 0),
                      "y_turns": float(yr.get("turns") or 0)})

    print("=" * 88)
    print("ТРАЕКТОРИЯ СЧЁТА В ДУЭЛИ: когда варианты расходятся, а не только в конце")
    print("=" * 88)
    print(f"  игр с записями: {len(games)}   горизонты: {horizons}"
          + (f"   отброшено из-за отказа стороны: {len(dead)} (игры {dead})"
             if dead else ""))
    if not games:
        print("  нет записей — вердикта нет (это «данных нет», а не «различий нет»)")
        return 0

    print()
    header = f"{'горизонт':>9}{'игр':>5}{'X счёт':>9}{'Y счёт':>9}{'Δ X−Y':>9}{'95% CI':>18}  вердикт"
    print(header)
    print("-" * 88)
    for h in horizons:
        diffs, xs, ys = [], [], []
        for g in games:
            # Игру берём только если ОБЕ стороны дошли до горизонта: иначе мы
            # сравним «X на 30-м ходу» с «Y на 12-м», что не сравнение.
            if min(g["x_turns"], g["y_turns"]) < h:
                continue
            sx = cumulative(g["x"].get("score_series") or [], upto=h)
            sy = cumulative(g["y"].get("score_series") or [], upto=h)
            xs.append(sx)
            ys.append(sy)
            diffs.append(sx - sy)
        if not diffs:
            print(f"{h:>9}{0:>5}   (ни одна игра не дошла до этого хода)")
            continue
        v = ab_verdict(diffs, args.min_games)
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        lo, hi = v["summary"]["ci"]
        mark = {"no_data": "мало игр", "no_difference": "различия нет",
                "difference": "РАЗЛИЧИЕ"}[v["verdict"]]
        print(f"{h:>9}{len(diffs):>5}{mean_x:>9.1f}{mean_y:>9.1f}"
              f"{v['summary']['mean']:>+9.1f}{f'[{lo:+.1f}, {hi:+.1f}]':>18}  {mark}")

    print()
    print("Оговорка: траектория — это приросты счёта в моменты, когда счёт менялся;")
    print("между событиями роста нет, и это норма (счёт редкий), а не пропуск данных.")
    print("Игру учитывают на горизонте только если ОБЕ стороны до него дошли.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())