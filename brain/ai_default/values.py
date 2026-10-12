"""Числа и правила встроенного ИИ-игрока Freeciv — перенос, а не наши догадки.

Зачем модуль. Владелец указал: наш ИИ строится на данных встроенного ИИ, а не на
изобретённых весах. Здесь собраны ЕГО числа и ЕГО порядок вычисления, ровно как в
исходниках, с указанием файла и строки. Ничего не подбиралось на глаз.

Источники (движок стенда, дерево `/docker/freeciv/freeciv/`):

* веса выходов — `server/advisors/advbuilding.h:19-21`
  (FOOD_WEIGHTING 30, SHIELD_WEIGHTING 17, TRADE_WEIGHTING 18);
* приоритеты — `server/advisors/advdata.c:499-508`
  (при желании науки: science_priority = 18*1.2 = 21.6, luxury_priority = 1; gold 18);
* оценка клетки и площадки — `ai/default/daisettler.c`
  (`cityresult_fill`: perfection ×1.5 при PERFECTION 3, `food >= 2` ⇒ ×2,
  crowdedness −15 за чужую работу; `city_desirability`: остальные клетки делятся на
  GROWTH_POTENTIAL_DEEMPHASIS 8, бонусы обороны и моря, вычет потерь);
* пороги отказа — `ai/default/daisettler.c` (`food_starvation`: центр + лучшая клетка
  по еде ≤ FOOD_COST; `shield_starvation`: те же две клетки дают 0 щитов);
* амортизация — `server/advisors/advtools.c:29` при `advtools.h:19` (`MORT 24`):
  `benefit * (1 - 1/24) ** delay`;
* прочие постоянные — `ai/default/daisettler.c`: `RESULT_IS_ENOUGH 250`,
  `FERRY_TECH_WANT 500`, `PERFECTION 3`, `GROWTH_PRIORITY 15`,
  `GROWTH_POTENTIAL_DEEMPHASIS 8`, `NAVAL_EMPHASIS 20`, `DEFENSE_EMPHASIS 20`.

Модуль чистый: только арифметика над выходами клеток. Состоянием мира он не владеет —
выходы клеток ему передаёт вызывающий.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Постоянные встроенного ИИ (имена — как в его исходниках).
PERFECTION: int = 3
GROWTH_PRIORITY: int = 15
GROWTH_POTENTIAL_DEEMPHASIS: int = 8
NAVAL_EMPHASIS: int = 20
DEFENSE_EMPHASIS: int = 20
MORT: int = 24
RESULT_IS_ENOUGH: int = 250
FERRY_TECH_WANT: int = 500


@dataclass(frozen=True)
class TileValue:
    """Оценка одной клетки в числах встроенного ИИ."""

    food: float
    shield: float
    trade: float
    sum: float
    reserved: int = 0


def tile_sum(food: float, shield: float, trade: float, *,
             food_priority: float, science_priority: float, shield_priority: float,
             reserved: int = 0, is_city_center: bool = False) -> TileValue:
    """`ptdc->sum` из `cityresult_fill` (daisettler.c), строка в строку.

    ``sum = food*food_priority + trade*science_priority + shield*shield_priority``
    (обратите внимание: торговля входит весом НАУКИ — отдельного слагаемого науки у
    встроенного ИИ нет), затем ``*= PERFECTION/2``, затем ``*= 2`` при ``food >= 2`` —
    ему «это нужно, чтобы расти». Чужая работа (``reserved``) вычитается в размере
    ``GROWTH_PRIORITY`` на единицу, но не больше, чем ``sum - 1``; центр города от
    этого вычета освобождён.
    """
    total = (food * food_priority
             + trade * science_priority
             + shield * shield_priority)
    total *= PERFECTION / 2
    if food >= 2:
        total *= 2
    if total > 0 and not is_city_center:
        total -= min(reserved * GROWTH_PRIORITY, total - 1)
    return TileValue(food=food, shield=shield, trade=trade, sum=total, reserved=reserved)


def amortize(benefit: float, delay: int) -> float:
    """`amortize` из `advtools.c:29` при `MORT = 24`."""
    discount = 1.0 - 1.0 / MORT
    return benefit * (discount ** max(0, int(delay)))


def food_starvation(center: TileValue, best_other: TileValue | None, food_cost: float) -> bool:
    """`food_starvation` (daisettler.c:558): центр плюс лучшая клетка ≤ FOOD_COST."""
    food = center.food + (best_other.food if best_other else 0.0)
    return food <= food_cost


def shield_starvation(center: TileValue, best_other: TileValue | None) -> bool:
    """`shield_starvation` (daisettler.c:573): щитов у этих двух клеток нет вовсе."""
    shields = center.shield + (best_other.shield if best_other else 0.0)
    return shields == 0


def site_total(center: TileValue, best_other: TileValue | None,
               others: list[TileValue]) -> float:
    """`result->total` для НОВОГО города (daisettler.c, ветка `virtual_city`).

    Площадка = центр + лучшая рабочая клетка; все прочие делятся на
    ``GROWTH_POTENTIAL_DEEMPHASIS`` и складываются («потенциал»). Бонусы обороны и
    моря сюда не входят: они нужны только на карте с террейном и водой, и я их
    добавляю отдельным слагаемым там, где эти данные есть.
    """
    total = center.sum + (best_other.sum if best_other else 0.0)
    total += sum(t.sum for t in others) / GROWTH_POTENTIAL_DEEMPHASIS
    return max(0.0, total)


def settler_want(total: float, *, travel_turns: int, settler_shield_cost: float) -> float:
    """`cr->result` из `settler_map_iterate` (daisettler.c).

    ``result = amortize(total, PERFECTION * turns) - стоимость поселенца``.
    Это и есть «нужда в поселенце»: площадка стоит тем меньше, чем дальше идти, и
    из неё вычитается сам поселенец — тем самым отсекаются мелкие пустышки.
    """
    return amortize(total, PERFECTION * max(0, travel_turns)) - settler_shield_cost