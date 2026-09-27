#!/usr/bin/env python
"""Порог, при котором исследование перевешивает производство — по ИЗМЕРЕННЫМ числам.

Правило берётся у самого прогноза, а не подбирается под результат:

    вклад(действие) = Δ ln(опции) × γ^срок          (γ = 0.8, штраф за необратимость
                                                     у производства и науки один и тот же)

Числа — из живых прогонов 2026-09-27 (дамп кандидатов, `--dump-candidates`):

  * технология: стоимость 28, «открывает» 5.60 опций (наблюдалось 5.60 и 4.71);
  * производство: Warriors 4.56 опций за 1–3 хода; Settlers 3.81 опции за 12 ходов;
  * наука за ход = round(Σ торговля × ставка / 100) — измеренный драйвер.

Альтернатива исследования для города — это ЛУЧШЕЕ производство, поэтому порог
считается как «при какой науке/ход срок технологии падает настолько, что вклад
исследования становится не меньше лучшего производственного вклада».

Печатается точка перехода, а не «мало/много»: при стоимости 28 «на глаз» ничего
не решается.
"""
import math

GAMMA = 0.8
IRREVERSIBLE_PENALTY = 0.05

#: Технология (измерено)
TECH_COST = 28.0
TECH_UNLOCKED = (5.60, 4.71)
#: Производство (измерено): (имя, опции, срок)
PRODUCTION = (("Warriors", 4.56, 1), ("Warriors", 4.56, 3),
              ("Settlers", 3.81, 12))


def value(options: float, turns: int) -> float:
    if options <= 0.0:
        return 0.0
    return math.log(options) * (GAMMA ** turns)


def main():
    best_production = max(value(o, t) for _n, o, t in PRODUCTION)
    print("Вклад производственных кандидатов (измерено):")
    for name, options, turns in PRODUCTION:
        print(f"  {name:9s} опции={options:5.2f} срок={turns:2d} → "
              f"вклад={value(options, turns):+.4f}")
    print(f"\nлучшее производство: {best_production:+.4f}")

    for options in TECH_UNLOCKED:
        ln_options = math.log(options)
        print(f"\nтехнология, открывающая {options:.2f} опций "
              f"(ln = {ln_options:.3f}), стоимость {TECH_COST:.0f}:")
        crossing = None
        for per_turn in range(1, 25):
            turns = max(1, math.ceil(TECH_COST / per_turn))
            contribution = value(options, turns)
            mark = ""
            if contribution >= best_production and crossing is None:
                crossing = per_turn
                mark = "  ← отсюда исследование не хуже лучшего производства"
            print(f"  наука/ход {per_turn:2d} → срок {turns:2d} → "
                  f"вклад {contribution:+.4f}{mark}")
        if crossing is None:
            print("  ВЕРДИКТ: при ставке 60% исследование не догоняет производство "
                  "даже при науке/ход 24 (нужен другой рычаг: дешевле технология, "
                  "либо дороже срок производства)")
        else:
            rate = 60.0
            trade_needed = crossing * 100.0 / rate
            print(f"  ВЕРДИКТ: порог — наука/ход ≥ {crossing}, то есть при ставке "
                  f"{rate:.0f}% торговля городов ≥ {trade_needed:.1f} "
                  f"(наука за ход = round(торговля × ставка / 100))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())