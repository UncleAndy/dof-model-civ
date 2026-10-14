"""§13.337: ветви `Shrink_Food` и `Popcost_Free` — по его коду, а не по нашим догадкам.

Источник: `ai/default/daieffects.c:301` и `:305`.

    case EFT_SHRINK_FOOD:
      v += c * 4 + (amount / 15) * MAX(-pcity->surplus[O_FOOD], 1);
    case EFT_POPCOST_FREE:
      v += amount * city_granary_size(pcity->size) / 10;

Сторож держит именно эти формулы: пока они совпадают, `Granary` (`Shrink_Food`) не может
молча вернуться к нулю — а это и был измеренный разрыв: житница стоила у нас `0.0`
(§13.327), то есть рычаг роста отбрасывался как «не оценённый предмет».
"""
from __future__ import annotations

from brain.ai_default import effects as fx


def test_shrink_food_is_his_formula() -> None:
    # c=1, amount=50: 1*4 + (50//15)*max(0,1) = 4 + 3 = 7
    assert fx.effect_value("Shrink_Food", 50, c=1, surplus_food=0.0) == 7.0
    # голод (отрицательный излишек) поднимает ценность: max(3,1)=3 -> 4 + 3*3
    assert fx.effect_value("Shrink_Food", 50, c=1, surplus_food=-3.0) == 13.0
    # целочисленное деление как в C: 14//15 == 0
    assert fx.effect_value("Shrink_Food", 14, c=1, surplus_food=0.0) == 4.0
    # три города в радиусе дают 3*4
    assert fx.effect_value("Shrink_Food", 14, c=3, surplus_food=0.0) == 12.0


def test_popcost_free_is_his_formula() -> None:
    # amount * granary_size // 10: 1 * 20 / 10 = 2 (в C деление целочисленное)
    assert fx.effect_value("Popcost_Free", 1, c=1, granary_size=20.0) == 2.0
    assert fx.effect_value("Popcost_Free", 3, c=1, granary_size=41.0) == 12.0  # 123//10


def test_granary_is_no_longer_priced_zero() -> None:
    """Житница мира (`Granary: Shrink_Food`) обязана быть оценена, а не молчать нулём."""
    from env import rules_costs as rc

    rows = [r for r in rc.EFFECTS if isinstance(r, (list, tuple))]
    value = fx.improvement_value(rows, "Granary", prod={"food": 0.0, "shields": 0.0},
                                 worked_tiles=2, num_cities=1, cities=1,
                                 surplus_food=0.0, granary_size=20.0)
    assert value > 0.0, "Granary снова ноль — ветвь Shrink_Food потеряна"
