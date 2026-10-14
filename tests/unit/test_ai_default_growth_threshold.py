"""Сторож переноса `min_food_surplus_for_fastest_growth` (`common/aicore/cm.c:1928`).

Формула перенесена, но НЕ подключена как замена порога из `cityturn.c:346-350`, и причина
замерена: у неё ПЕРВЫЙ выход срабатывает у почти любого настоящего города, и значение выходит
нулевым или отрицательным — то есть слабее. Обе половины держатся сторожем: и его арифметика,
и этот замер. Числа посчитаны рукой по его строкам, а не сняты с нашей реализации.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brain.ai_default.city_manager import (  # noqa: E402
    MIN_SURPLUS_FOOD,
    granary_size,
    min_food_surplus_for_fastest_growth as fastest_growth,
)


def test_first_exit_dominates_for_real_cities():
    """Его строки 6/17-24: `max_surplus = −еда_на_жителя × размер + еда СВОБОДНЫХ клеток центра`.

    Город растёт, только если центр сам кормит всех, — а это редкость: центр 1–4 еды при
    2 еды на жителя. Поэтому у живых городов функция возвращает 0 или отрицательное.
    """
    # размер 2, еда на жителя 2, центр 1 → −4 + 1 = −3 (ранний выход)
    assert fastest_growth(city_size=2, food_stock=0, food_cost=2, center_food=1,
                          tile_foods=[3, 3, 2]) == -3
    # размер 1, еда на жителя 2, центр 2 → 0 (ранний выход: `if (max_surplus <= 0)`)
    assert fastest_growth(city_size=1, food_stock=0, food_cost=2, center_food=2,
                          tile_foods=[3]) == 0


def test_full_granary_means_no_food_needed():
    """`if (food_needed <= 0) return 0` — до этой строки надо пройти ранний выход.

    Центр 3 еды при 1 еде на жителя и размере 1 даёт 2 > 0 — идём дальше; склад полон → 0.
    """
    assert granary_size(1) == 20
    assert fastest_growth(city_size=1, food_stock=20, food_cost=1, center_food=3,
                          tile_foods=[1]) == 0


def test_fastest_growth_threshold_is_his_two_lines():
    """`min_turns = ceil(need / max_surplus)`, порог = `ceil(need / min_turns)`.

    размер 1, еда на жителя 1, центр 3, склад 0: max_surplus 2; лучшая клетка 3 → 5;
    need = житница 20; min_turns = ceil(20/5) = 4; порог = ceil(20/4) = 5.
    """
    assert fastest_growth(city_size=1, food_stock=0, food_cost=1, center_food=3,
                          tile_foods=[3, 1]) == 5


def test_only_the_best_tiles_are_counted_up_to_the_number_of_workers():
    """У него цикл кончается по `workers`: лишние клетки в счёт НЕ идут.

    Размер 1 — кормится один житель, значит берётся ровно одна лучшая клетка: набор
    `[9, 1]` и набор `[9, 9, 9, 9]` обязаны дать ОДНО И ТО ЖЕ число (в обоих случаях это 10:
    max_surplus 2 + 9 = 11, need 20, min_turns = 2, порог = ceil(20/2)).
    """
    few = fastest_growth(city_size=1, food_stock=0, food_cost=1, center_food=3,
                         tile_foods=[9, 1])
    many = fastest_growth(city_size=1, food_stock=0, food_cost=1, center_food=3,
                          tile_foods=[9, 9, 9, 9])
    assert few == many == 10


def test_it_is_weaker_than_his_threshold_from_cityturn():
    """Замер, ради которого формула НЕ подключена: у живых городов она слабее порога `1`.

    Наблюдённые города: `(47,20)` размера 2 с центром 1 еды и складом 2; `(45,18)` размера 2 с
    центром 4 еды и складом 0. Её значения — −3 и 0.
    """
    assert fastest_growth(city_size=2, food_stock=2, food_cost=2, center_food=1,
                          tile_foods=[3, 2, 2, 1]) < MIN_SURPLUS_FOOD
    assert fastest_growth(city_size=2, food_stock=0, food_cost=2, center_food=4,
                          tile_foods=[3, 2, 2, 1]) < MIN_SURPLUS_FOOD
