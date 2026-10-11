#!/usr/bin/env python3
"""Линейка по ВСЕМ игрокам: очки игры, которые стенд пишет сам.

Владелец объявил (§13.125): сторон не менее шести, война — **любые нападения**, и счёт с DoF считаем в
трёх вариантах — сумма, среднее, разброс по игрокам. Целевая величина — **счёт игры** (§13.126).

Оказалось, что эта линейка не требует ни нашего агента, ни наблюдателя: по каждой партии стенд сам
складывает `game_scores/<время>-<слот>/{players.json,evaluations.json}` — **по каждому игроку ряд по
ходам** и по 16 категориям (`score`, `population`, `production`, `cities`, `military_units`, `gold`,
`units_killed`, `units_lost`, `land_area`…). Значит мера внешняя, одинаковая во всех играх и не зависит от
того, что сторона успела увидеть под туманом.

    .venv/bin/python scripts/game_scores_report.py --dir game_scores/2026-10-11-01:35:04-6301
    .venv/bin/python scripts/game_scores_report.py --latest 3 --war
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics as st

ROOT = pathlib.Path(__file__).resolve().parent.parent
WAR_KEYS = ("units_killed", "units_lost")
VARIANT_KEYS = ("score", "population", "military_units", "land_area", "gold")


def _load(d: pathlib.Path) -> tuple[dict, dict]:
    players = json.loads((d / "players.json").read_text(encoding="utf-8"))
    evals = json.loads((d / "evaluations.json").read_text(encoding="utf-8"))
    return players, evals


def _last(series: dict) -> dict:
    return {pid: (v[-1] if v else None) for pid, v in series.items()}


def _spread(values: list[float]) -> tuple[float, float, float, float]:
    return min(values), max(values), max(values) - min(values), (
        st.pstdev(values) if len(values) > 1 else 0.0)


def _report_dir(d: pathlib.Path, show_war: bool) -> dict:
    players, evals = _load(d)
    score = evals.get("score", {})
    finals = _last(score)
    names = {pid: (players.get(pid, {}) or {}).get("name", f"игрок {pid}") for pid in score}
    turns = max((len(v) for v in score.values()), default=0)

    print("=" * 96)
    print(f"ПАРТИЯ {d.name}: очки всех игроков (ходит записано {turns})")
    print("=" * 96)
    head = f"{'игрок':>8} {'имя':>8} {'счёт':>6} {'прирост':>8} {'население':>10} {'армия':>6} {'земля':>8}"
    print(head)
    print("-" * len(head))
    for pid in sorted(score, key=lambda p: (finals.get(p) or 0), reverse=True):
        series = score[pid]
        gain = (series[-1] - series[0]) if len(series) >= 2 else 0
        pop = _last(evals.get("population", {})).get(pid)
        mil = _last(evals.get("military_units", {})).get(pid)
        land = _last(evals.get("land_area", {})).get(pid)
        print(f"{pid:>8} {names.get(pid,''):>8} {finals.get(pid, 0):>6} {gain:>8} "
              f"{pop:>10} {mil:>6} {land:>8}")

    values = [float(v) for v in finals.values() if v is not None]
    lo, hi, rng, sd = _spread(values)
    print()
    print("ОБЪЯВЛЕННЫЕ ВАРИАНТЫ (§13.125) по всем игрокам:")
    print(f"  счёт игры: сумма {sum(values):.2f}; среднее {st.mean(values):.2f}; "
          f"разброс min {lo:.0f} / max {hi:.0f} / диапазон {rng:.0f} / σ {sd:.2f}")

    for key in VARIANT_KEYS[1:]:
        series = evals.get(key) or {}
        vals = [float(v) for v in _last(series).values() if v is not None]
        if not vals:
            continue
        lo2, hi2, rng2, sd2 = _spread(vals)
        print(f"  {key}: сумма {sum(vals):.2f}; среднее {st.mean(vals):.2f}; "
              f"разброс {lo2:.0f}…{hi2:.0f} / σ {sd2:.2f}")

    war = {k: _last(evals.get(k, {})) for k in WAR_KEYS}
    killed = sum(int(v or 0) for v in war["units_killed"].values())
    lost = sum(int(v or 0) for v in war["units_lost"].values())
    killers = sorted(pid for pid, v in war["units_killed"].items() if (v or 0) > 0)
    print()
    print(f"  война по объявленному правилу (любое нападение): "
          f"{'БЫЛА' if killed else 'не было'}; убито чужих юнитов {killed}, "
          f"потеряно своих {lost}; у кого есть убитые чужие "
          f"(НЕ признак нападения: сюда входят и убийства в обороне): "
          f"{killers or '—'}")
    if show_war:
        for key in WAR_KEYS:
            by_turn = {}
            for pid, series in (evals.get(key) or {}).items():
                for turn_no, value in enumerate(series):
                    if value:
                        by_turn.setdefault(turn_no, []).append((pid, value))
            print(f"    {key} по ходам:", by_turn or "нет")

    return {
        "dir": d.name,
        "players": players,
        "score_final": finals,
        "score_sum": sum(values),
        "score_mean": st.mean(values),
        "score_spread": {"min": lo, "max": hi, "range": rng, "std": sd},
        "war": {"killed": killed, "lost": lost, "killer_players": killers},
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default=None, help="каталог одной партии")
    p.add_argument("--latest", type=int, default=0, help="сколько последних партий взять")
    p.add_argument("--war", action="store_true", help="печатать нападения по ходам")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    base = ROOT / "game_scores"
    if args.dir:
        dirs = [pathlib.Path(args.dir) if pathlib.Path(args.dir).is_absolute()
                else ROOT / args.dir]
    else:
        dirs = sorted((d for d in base.iterdir() if d.is_dir()),
                      key=lambda d: d.stat().st_mtime)[-max(1, args.latest):]
    if not dirs:
        print("партий не найдено")
        return 2

    summaries = [_report_dir(d, args.war) for d in dirs if (d / "evaluations.json").exists()]
    if args.out and summaries:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nсводка сохранена: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
