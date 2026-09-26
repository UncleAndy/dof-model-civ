"""Сравнение агентов по СЧЁТУ ИГРЫ — метрике, не выведенной из наблюдения.

Зачем отдельный анализатор. Все прежние сравнения опирались на индекс DoF,
посчитанный по `obs`, а канал наблюдения зависит от поведения: агент, который
ничего не делает, получает меньше пакетов (замерено: у no-op в наблюдении нет
даже собственного города). Поэтому разница «агент против no-op» по таким
метрикам измеряет канал, а не игру.

Счёт игры считает сервер и отдаёт приростом (`current_score - last_score`), для
всех агентов одинаково. Первый прирост — это стартовый счёт, а не выигрыш,
поэтому выигрыш = сумма приростов минус первый (`score_gain`).

Честные оговорки, которые печатаются всегда:
* величина счёта мала (единицы за десятки ходов), поэтому N должен быть большой;
* матч, который стенд не отдал (`turns` мало, сущностей ноль), не засчитывается;
* счёт — это одна сторона игры (рост и развитие); он не говорит, «хороша ли
  стратегия» вообще, он говорит, двигала ли она счёт сильнее, чем бездействие.

    python scripts/analyze_score.py results.json [--min-turns 40]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics.stats import bootstrap_diff_ci, ci95, cohens_d, mean  # noqa: E402

#: Агенты, у которых «ноль действий» — это норма (бездействие и есть стратегия).
PASSIVE_AGENTS = ("no-op",)


def valid(record: dict, min_turns: int) -> bool:
    """Годится ли матч: стенд отдал игру и агент в ней вообще был."""
    if record.get("error") or record.get("wedge_action"):
        return False
    if float(record.get("turns") or 0) < min_turns:
        return False
    if float(record.get("min_entities") or 0) <= 0:
        return False
    return True


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+", help="JSON-выгрузки прогонов")
    p.add_argument("--min-turns", type=int, default=40)
    p.add_argument("--baseline", default="no-op",
                   help="с кем сравнивать (по умолчанию no-op)")
    args = p.parse_args()

    per_agent: dict[str, list[dict]] = {}
    dropped: dict[str, int] = {}
    for path in args.files:
        payload = json.loads(Path(path).read_text())
        for agent, records in payload.get("results", {}).items():
            kept = [r for r in records if valid(r, args.min_turns)]
            per_agent.setdefault(agent, []).extend(kept)
            dropped[agent] = dropped.get(agent, 0) + (len(records) - len(kept))

    print("=" * 86)
    print("Счёт игры по агентам (серверная метрика, не из наблюдения)")
    print("=" * 86)
    print(f"{'агент':<22}{'n':>4}{'счёт↑':>9}{'95% CI':>20}"
          f"{'событий':>9}{'решений/ход':>13}")
    print("-" * 86)
    for agent, records in sorted(per_agent.items()):
        if not records:
            print(f"{agent:<22}{0:>4}   (нет пригодных матчей)")
            continue
        gains = [float(r.get("score_gain") or 0.0) for r in records]
        lo, hi = ci95(gains)
        events = mean([float(r.get("score_events") or 0.0) for r in records])
        dec = mean([float(r.get("decisions_per_turn_mean") or 0.0) for r in records])
        print(f"{agent:<22}{len(gains):>4}{mean(gains):>9.1f}"
              f"{f'[{lo:+.1f}, {hi:+.1f}]':>20}{events:>9.1f}{dec:>13.2f}")

    print()
    print("СРАВНЕНИЕ С БАЗОЙ (" + args.baseline + ")")
    base = per_agent.get(args.baseline) or []
    if not base:
        print("  нет пригодных матчей базы — сравнивать не с чем")
    else:
        base_gains = [float(r.get("score_gain") or 0.0) for r in base]
        for agent, records in sorted(per_agent.items()):
            if agent == args.baseline or not records:
                continue
            gains = [float(r.get("score_gain") or 0.0) for r in records]
            lo, hi, diff = bootstrap_diff_ci(gains, base_gains)
            star = "  <- значимо" if (lo > 0 or hi < 0) and min(len(gains), len(base_gains)) >= 4 else ""
            # d по одному-двум матчам — не «эффекта нет», а «не из чего считать»:
            # лучше прочерк, чем ноль, который прочитают как вывод.
            if min(len(gains), len(base_gains)) >= 4:
                d_txt = f"d = {cohens_d(gains, base_gains):+.2f}"
            else:
                d_txt = "d = —  (мало матчей)"
            print(f"  {agent:<22} Δ = {diff:+7.1f}  95% CI [{lo:+.1f}, {hi:+.1f}]"
                  f"   {d_txt}{star}")
        print(f"  база {args.baseline}: {mean(base_gains):+.1f} "
              f"({len(base_gains)} матчей)")

    if dropped:
        print()
        print(f"  отброшено матчей: {dropped}")
    print()
    print("Оговорки:")
    print(" * Счёт мал по величине: на десятках ходов это единицы очков, поэтому")
    print("   N должен быть большим, а широкий CI — это «мало данных», не «нет эффекта».")
    print(" * Отброшенный матч — факт о стенде: без этого фильтра ранние обрывы")
    print("   (turns 2–5, пустой мир) попали бы в средние как «слабая игра».")
    print(" * Валидна именно эта метрика для сравнения с бездействием: у no-op нет")
    print("   ни действий, ни пакетов наблюдения, и метрики по obs сравнение не выдержат.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
