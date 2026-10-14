"""Городской управляющий: как СЕРВЕР распределяет жителей по клеткам.

Почему не `ai/default`. Работы рабочего (ирригация, шахта, дорога) и распределение ЖИТЕЛЕЙ —
разные решения. Первое у него в `server/advisors/autoworkers.c` (`settler_evaluate_improvements`,
`consider_settler_action`), второе — в общем коде города: `server/cityturn.c:313`
(`set_default_city_manager`), вызываемом из `auto_arrange_workers` (`:366`). Эталон для клетки
жителя — здесь, и числа берутся оттуда дословно, а не назначаются.

Зачем это вообще. Прежняя наша оценка клетки — «формулой города (Δ опций)», то есть НАШ предмет.
У его управляющего предмет другой, и в нём есть то, чего у нас не было: ОБЯЗАТЕЛЬНЫЙ прирост
пищи (иначе город не растёт) и вес пищи, зависящий от размера города. Отсюда и подозрение на
разрыв −1 по населению (§13.223).
"""

from __future__ import annotations

import math

# ── Веса управляющего (`cityturn.c:325-352`, дословно) ──────────────────────────────
#: Пища, город размера 1: «Growing to size 2 is the highest priority».
FOOD_FACTOR_GROWING_TO_TWO = 20
#: Пища, размер ≤ `notradesize`.
FOOD_FACTOR_SMALL = 15
#: Пища, размер > `notradesize` (и житница не полна).
FOOD_FACTOR_NORMAL = 10
#: Пища при ПОЛНОЙ житнице: «We don't need more food if the granary is full».
FOOD_FACTOR_GRANARY_FULL = 0
SHIELD_FACTOR = 5
GOLD_FACTOR = 2
SCIENCE_FACTOR = 2
#: «Trade only provides gold/science» — сама торговля веса не имеет.
TRADE_FACTOR = 0
#: «Luxury only influences happiness».
LUXURY_FACTOR = 0
HAPPY_FACTOR = 0

#: Наименьшие приросты (`cityturn.c:353-366`): голод и безщитовой город недопустимы как
#: ГОРОД, поэтому управляющий их не выбирает, а не «оценивает ниже».
MIN_SURPLUS_FOOD = 1
MIN_SURPLUS_FOOD_GRANARY_FULL = 0
MIN_SURPLUS_SHIELD = 1

# ── Числа мира, нужные для ветки «житница полна» ─────────────────────────────────────
#: `GAME_DEFAULT_NOTRADESIZE` (`common/game.h:637`) — в classic 0, то есть ветка «размер ≤
#: notradesize» (вес 15) недостижима, и вес пищи равен 20 при размере 1 и 10 иначе.
NOTRADESIZE = 0
#: `classic/game.ruleset`: `granary_food_ini = 20`, `granary_food_inc = 10`.
GRANARY_FOOD_INI = 20
GRANARY_FOOD_INC = 10
#: `granary_num_inis` — из правил; при нуле/отсутствии правила ставят единицу
#: (`server/ruleset.c:6771`).
GRANARY_NUM_INIS = 1
#: `GAME_DEFAULT_FOODBOX` (`common/game.h:410`).
FOODBOX = 100


def granary_size(city_size: int) -> int:
    """`city_granary_size` (`common/city.c:2108`) на числах classic."""
    if city_size <= 0:
        return 0
    if city_size > GRANARY_NUM_INIS:
        base = GRANARY_FOOD_INI + GRANARY_FOOD_INC * (city_size - GRANARY_NUM_INIS)
    else:
        base = GRANARY_FOOD_INI
    return max(base * FOODBOX // 100, 1)


def granary_full(city_size: int, food_stock: float | None) -> bool:
    """Полна ли житница — его проверка `gsize == pcity->food_stock`.

    Незнание склада еды НЕ считается «полной житницей»: иначе вес пищи падал бы до нуля
    там, где мы просто не знаем склада.
    """
    if food_stock is None:
        return False
    return float(food_stock) >= float(granary_size(int(city_size)))


def food_factor(city_size: int, granary_is_full: bool) -> int:
    """Вес пищи по размеру города (`cityturn.c:325-340`)."""
    if int(city_size) > 1:
        if int(city_size) <= NOTRADESIZE:
            return FOOD_FACTOR_SMALL
        return FOOD_FACTOR_GRANARY_FULL if granary_is_full else FOOD_FACTOR_NORMAL
    return FOOD_FACTOR_GROWING_TO_TWO


def score(food: float, shield: float, gold: float, science: float,
          city_size: int, granary_is_full: bool) -> float:
    """Взвешенная сумма управляющего — то, что он максимизирует.

    Торговля и роскошь веса не имеют (его слова), поэтому в сумму не входят: их вклад идёт
    через золото и науку, на которые торговля делится ставками.
    """
    return (float(food) * food_factor(city_size, granary_is_full)
            + float(shield) * SHIELD_FACTOR
            + float(gold) * GOLD_FACTOR
            + float(science) * SCIENCE_FACTOR)


def min_food_surplus_for_fastest_growth(*, city_size: int, food_stock: float, food_cost: float,
                                        center_food: float, tile_foods=(), specialists: int = 0
                                        ) -> int:
    """Порог пищи ПОД СКОРЕЙШИЙ РОСТ — его `min_food_surplus_for_fastest_growth`
    (`common/aicore/cm.c:1928`), а не наши постоянные 1/0.

    Почему это важно. При `max_growth` он НЕ берёт постоянный порог: `cm.c:1992-1995`
    подменяет `minimal_surplus[O_FOOD]` этим числом. Значит город обязан держать прирост,
    дающий скорейший рост, — а не просто «не меньше единицы». Измерено у нас: город размера 2
    с излишком 0 стоял и не рос, хотя это ровно то, что его порог запрещает.

    Формула, слагаемое в слагаемое:

        max_surplus = −food_cost × размер + еда свободных клеток центра
        если max_surplus <= 0      → вернуть его (отрицательным: ограничение снимается)
        need = размер_житницы(размер) − склад;   если need <= 0 → 0 (житница полна)
        добрать лучшими по еде клетками, пока не кончатся жители, которых надо кормить
            (специалисты еды не дают и в счёт не идут)
        min_turns = ceil(need / max_surplus)
        порог = ceil(need / min_turns)
    """
    size = int(city_size or 0)
    surplus = -float(food_cost or 0.0) * size
    surplus += float(center_food or 0.0)
    if surplus <= 0.0:
        return int(surplus)
    need = granary_size(size) - float(food_stock or 0.0)
    if need <= 0.0:
        return 0
    workers = max(0, size - int(specialists or 0))
    for food in sorted((float(f) for f in tile_foods), reverse=True):
        if workers <= 0:
            break
        surplus += food
        workers -= 1
    if surplus <= 0.0:
        return int(surplus)
    min_turns = math.ceil(need / surplus)
    if min_turns <= 0:
        return 0
    return math.ceil(need / min_turns)


def minimums_ok(food_surplus: float | None, shield_surplus: float | None,
                granary_is_full: bool, food_need: int | None = None) -> bool:
    """Наименьшие приросты управляющего.

    Незнание прироста не запрещает: запрет выдаётся только на ИЗМЕРЕННОМ нарушении
    («незнание ≠ отсутствие возможностей»). Но если прирост известен и ниже порога — вариант
    отвергается: это его `minimal_surplus`, а не наш порог.
    """
    if food_surplus is not None:
        if food_need is not None:
            need = int(food_need)          # его число для скорейшего роста (`cm.c:1928`)
        else:
            need = MIN_SURPLUS_FOOD_GRANARY_FULL if granary_is_full else MIN_SURPLUS_FOOD
        if float(food_surplus) < need:
            return False
    if shield_surplus is not None and float(shield_surplus) < MIN_SURPLUS_SHIELD:
        return False
    return True