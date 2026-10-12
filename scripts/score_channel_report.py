"""Отчёт по каналу стенда: все игроки, один и тот же ход, внутри одной партии.

Зачем отдельный скрипт. Прежние сравнения мешали несравнимое: суммы по четырём
нашим местам против одного места, партии разной длины, внутренний счёт раннера
против счёта стенда. Канал стенда (`game_scores/<время>-<слот>/evaluations.json`)
даёт то, что нужно: по каждому игроку ряда по ходам. Здесь берётся один и тот же
ход у ВСЕХ мест и наш ряд сравнивается с рядами встроенного ИИ внутри той же партии.

Запуск:  .venv/bin/python scripts/score_channel_report.py [число партий] [ход]
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANNEL = ROOT / "game_scores"
OUR_SEAT = "0"


def load(game_dir: pathlib.Path) -> dict[str, list] | None:
    f = game_dir / "evaluations.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {k: v for k, v in data.items() if isinstance(v, dict)} or None


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    turn = int(sys.argv[2]) if len(sys.argv) > 2 else 45
    if not CHANNEL.is_dir():
        print("канала нет:", CHANNEL)
        return
    dirs = sorted((d for d in CHANNEL.iterdir() if d.is_dir()), key=lambda d: d.name)[-limit:]
    print(f"Канал стенда: {CHANNEL.name}, партий взято {len(dirs)}, срез на {turn}-м ходу")
    print(f"{'партия':<26}{'ходов':>6}{'наш':>6}{'ИИ средн.':>11}{'ИИ разброс':>12}{'ранг':>6}")
    rows: list[tuple[str, int, float, float, int]] = []
    for d in dirs:
        data = load(d)
        if not data or not data.get("score", {}).get(OUR_SEAT):
            continue
        series = data["score"]
        ours_series = series[OUR_SEAT]
        turns = len(ours_series)
        i = min(turn - 1, turns - 1)
        ours = ours_series[i]
        others = [v[i] for k, v in series.items() if k != OUR_SEAT and len(v) > i]
        if not others:
            continue
        avg = sum(others) / len(others)
        spread = max(others) - min(others)
        rank = 1 + sum(1 for o in others if o > ours)
        print(f"{d.name:<26}{turns:>6}{ours:>6}{avg:>11.1f}{spread:>12}{rank:>6}")
        rows.append((d.name, turns, float(ours), avg, rank))

    if not rows:
        print("нет пригодных записей")
        return
    n = len(rows)
    print(f"\nИтого: партий {n}; наш счёт {min(r[2] for r in rows):.0f}…{max(r[2] for r in rows):.0f}, "
          f"встроенный ИИ {min(r[3] for r in rows):.1f}…{max(r[3] for r in rows):.1f}")
    print(f"Наш ранг: лучший {min(r[4] for r in rows)}, худший {max(r[4] for r in rows)} из 4 мест")
    better = sum(1 for r in rows if r[4] == 1)
    print(f"Партий, где мы впереди всех: {better} из {n}")


if __name__ == "__main__":
    main()