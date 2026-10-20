"""Шкалы желаний встроенного ИИ — перенос значений как есть (шаг 2 плана PORT_DAICITY_PLAN).

Здесь только КОНСТАНТЫ и чистые функции пересчёта шкал, без побочных эффектов: каркас выбора
производства (`choose_build`) будет строиться поверх них отдельным этапом. Модуль ни к чему не
подключён намеренно — чтобы не появилась ещё одна «мёртвая ветвь», которую потом примут за рабочий путь.

Источники (freeciv 3.x, `drafts/reference/freeciv-src`):
* `ai/default/daitools.h:31-33` — `DAI_WANT_BELOW_MIL_EMERGENCY`, `DAI_WANT_DOMESTIC_MAX`;
* `ai/default/daicity.c` — `RESULT_IS_ENOUGH`, `GROWTH_POTENTIAL_DEEMPHASIS`, `PERFECTION`, `MORT`;
* `ai/default/daitools.h` — `WORKER_FACTOR`;
* `ai/default/daicity.c` — `AI_CITY_RECALC_SPEED`.
"""

#: Порог «ниже военной тревоги»: желания внутренних нужд держатся под ним.
DAI_WANT_BELOW_MIL_EMERGENCY = 1000.0

#: Потолок желаний внутреннего советника.
DAI_WANT_DOMESTIC_MAX = 750.075

#: «Этого достаточно» — дальше желание не растим.
RESULT_IS_ENOUGH = 250

#: Во сколько раз недооценивается потенциал роста при расчёте.
GROWTH_POTENTIAL_DEEMPHASIS = 8

#: Точность, с которой считается «идеально».
PERFECTION = 3

#: Порог смертности города (голод).
MORT = 24

#: Множитель веса рабочего.
WORKER_FACTOR = 1024

#: Пересчёт желаний города раз в `rand(speed) + speed` ходов.
AI_CITY_RECALC_SPEED = 5


def below_mil_emergency(want: float) -> float:
    """Ограничить желание внутренней нужды сверху порогом военной тревоги.

    Его правило: внутренние желания не должны перебивать военную тревогу, поэтому они живут
    в шкале ниже `DAI_WANT_BELOW_MIL_EMERGENCY`.
    """
    return min(float(want), DAI_WANT_BELOW_MIL_EMERGENCY)


def domestic_capped(want: float) -> float:
    """Ограничить желание внутреннего советника его потолком."""
    return min(float(want), DAI_WANT_DOMESTIC_MAX)


def enough(want: float) -> bool:
    """Достигнуто ли «достаточно» — дальше желание не увеличиваем."""
    return float(want) >= RESULT_IS_ENOUGH


def recalc_period(rand_value: int) -> int:
    """Сколько ходов до следующего пересчёта желаний: `rand(speed) + speed`."""
    return int(rand_value) + AI_CITY_RECALC_SPEED
