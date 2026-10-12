"""Отчёт по каналу стенда: все игроки, один и тот же ход, внутри одной партии.

Зачем отдельный скрипт. Прежние сравнения мешали несравнимое: суммы по четырём
нашим местам против одного места, партии разной длины, внутренний счёт раннера
против счёта стенда. Канал стенда (`game_scores/<время>-<слот>/evaluations.json`)
даёт то, что нужно: по каждому игроку ряда по ходам. Здесь берётся один и тот же
ход у ВСЕХ мест и наш ряд сравнивается с рядами встроенного ИИ внутри той же партии.

Срез идёт ПО КАТЕГОРИИ, а не только по счёту: §13.198 показал, что счёт — плохая
мера (он считает юнитов), и вердикт ставится по населению, городам и земле.
Парная разность считается внутри партии (наш минус медиана ИИ на том же ходу),
затем берётся медиана этих разностей по всем партиям — это и есть величина
объявленного порога (§10.95, §13.191).

Запуск:  .venv/bin/python scripts/score_channel_report.py [число партий] [ход] [категория]
Пример:  .venv/bin/python scripts/score_channel_report.py 12 45 population
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANNEL = ROOT / "game_scores"
OUR_SEAT = "0"

#: Категории, которые стенд публикует по каждому игроку (проверяются наличием ключа).
CATEGORIES = ("score", "population", "cities", "land_area", "production",
              "researched_techs", "military_units", "units_built")


def load(game_dir: pathlib.Path) -> dict[str, dict] | None:
    f = game_dir / "evaluations.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {k: v for k, v in data.items() if isinstance(v, dict)} or None


def rows_for(data: dict, category: str, turn: int) -> tuple[float, list[float], int] | None:
    """Наш ряд и ряды встроенного ИИ на ОДНОМ ходу внутри одной партии."""
    series = data.get(category)
    if not isinstance(series, dict) or not series.get(OUR_SEAT):
        return None
    ours_series = series[OUR_SEAT]
    turns = len(ours_series)
    i = min(turn - 1, turns - 1)
    ours = float(ours_series[i])
    others = [float(v[i]) for k, v in series.items() if k != OUR_SEAT and len(v) > i]
    if not others:
        return None
    return ours, others, turns


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def sign_test(wins: int, total: int) -> float:
    """Односторонний знаковый тест: p = P(X ≥ wins) при честной монете."""
    if total <= 0:
        return 1.0
    tails = sum(math.comb(total, k) for k in range(wins, total + 1))
    return tails / (2 ** total)


def report(category: str, limit: int, turn: int) -> None:
    dirs = sorted((d for d in CHANNEL.iterdir() if d.is_dir()), key=lambda d: d.name)[-limit:]
    picked: list[tuple[str, float, float, float, int]] = []
    for d in dirs:
        data = load(d)
        if not data:
            continue
        got = rows_for(data, category, turn)
        if got is None:
            continue
        ours, others, turns = got
        ai_median = median(others)
        picked.append((d.name, ours, ai_median, max(others), turns))
    if not picked:
        print(f"нет пригодных записей по категории {category}")
        return

    print(f"Канал стенда, категория «{category}», партий {len(picked)}, срез на {turn}-м ходу")
    print(f"{'партия':<26}{'ходов':>6}{'наш':>8}{'ИИ медиана':>12}{'ИИ лучший':>11}{'разность':>10}")
    diffs: list[float] = []
    for name, ours, ai_median, ai_best, turns in picked:
        diff = ours - ai_median
        diffs.append(diff)
        print(f"{name:<26}{turns:>6}{ours:>8.0f}{ai_median:>12.1f}{ai_best:>11.1f}{diff:>+10.1f}")

    med = median(diffs)
    wins = sum(1 for d in diffs if d > 0)
    p_value = sign_test(wins, len(diffs))
    control_med = median([max(0.0, -d) for d in diffs])   # насколько мы отстаём
    print(f"\nПарная разность (наш минус медиана ИИ на том же ходу):")
    print(f"  медиана разностей: {med:+.2f}")
    print(f"  из {len(diffs)} партий лучше ИИ: {wins}; знаковый тест p = {p_value:.4f}")
    print(f"  порог §10.95: медиана ≥ +2.0 и ≥ 10 % отставания ({control_med:.1f}) ⇒ "
          f"{'выполнен' if (med >= 2.0 and med >= 0.1 * control_med and p_value < 0.05) else 'НЕ выполнен'}")


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    turn = int(sys.argv[2]) if len(sys.argv) > 2 else 45
    category = sys.argv[3] if len(sys.argv) > 3 else "population"
    if not CHANNEL.is_dir():
        print("канала нет:", CHANNEL)
        return
    if category == "все":
        for cat in CATEGORIES:
            report(cat, limit, turn)
            print()
        return
    report(category, limit, turn)


if __name__ == "__main__":
    main()