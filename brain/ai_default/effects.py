"""ЦЕННОСТЬ ЭФФЕКТА МИРА — порт его оценки, числа не выдуманы.

Источник: `ai/default/daieffects.c` (в контейнере стенда —
`/docker/freeciv/freeciv/ai/default/daieffects.c`): `dai_content_effect_value` (стр. 77)
и `dai_effect_value` (стр. 138). Веса — из `server/advisors/advbuilding.h`.

Зачем это нам. Ценность типа производства (улучшения или юнита) он собирает не «на глаз», а
как сумму ценностей ЭФФЕКТОВ этого типа: `daicity.c:1860` накапливает
`building_want[id] += v`, где `v` считается здесь. Значит, имея эффекты мира (прочитаны
`scripts/read_rules_costs.py`) и эту функцию, мы можем посчитать ценность ЛЮБОГО типа, не
видя его живьём и не ставя проб. Это указание владельца: «код встроенного ИИ — это тоже
наблюдение, можно использовать значения из него».

Что портировано не полностью (честно):
  * часть эффектов его код в этой функции ПРОПУСКАЕТ — они уже учтены в `base_want()`
    (перечень ниже, `COUNTED_IN_BASE_WANT`); для них здесь ноль, и это не пробел, а его же
    устройство;
  * `user_effect_ai_valued_as` (перенаправление вида эффекта) не портирован — в классических
    правилах он сводится к тождественному отображению;
  * промежуточные ступени счастья (`feel[..][FEELING_EFFECT]`) наблюдение не публикует —
    стенд отдаёт только итоговые `ppl_*`. Порт использует итоговые, что совпадает с его
    результатом всюду, где промежуточные ступени не ниже итоговой (комментарий в
    `content_value`).
"""

from __future__ import annotations

#: Веса его кода (`ai/default/daieffects.c`), выписаны с указанием строк.
CONTENT_WEIGHT = 35          # EFT_MAKE_CONTENT: * 35 на каждого переведённого (стр. 214)
MAKE_HAPPY_WEIGHT = 5        # EFT_MAKE_HAPPY: * 5 (стр. 182)
NO_UNHAPPY_WEIGHT = 30       # EFT_NO_UNHAPPY: * 30 (стр. 190)
MAKE_CONTENT_MIL_WEIGHT = 25  # EFT_MAKE_CONTENT_MIL_PER (стр. 221)
MAKE_CONTENT_MIL_PER_CITY = 5  # EFT_MAKE_CONTENT_MIL_PER: MIN(amount, 5) * c (стр. 222)

#: Эффекты, которые его `dai_effect_value` пропускает: они уже учтены в `base_want()`
#: (`daieffects.c:174-205`, ветка `case` без действий).
COUNTED_IN_BASE_WANT: frozenset[str] = frozenset({
    "Capital_City", "Gov_Center", "Upkeep_Free", "Tech_Upkeep_Free",
    "Pollu_Pop_Pct", "Pollu_Pop_Pct_2", "Pollu_Prod_Pct",
    "Output_Bonus", "Output_Bonus_Absolute", "Output_Bonus_2",
    "Output_Add_Tile", "Output_Inc_Tile", "Output_Per_Tile",
    "Output_Waste", "Output_Waste_By_Distance", "Output_Waste_By_Rel_Distance",
    "Output_Waste_Pct", "Surplus_Waste_Pct", "Surplus_Waste_Pct_By_Rel_Distance",
    "Specialist_Output", "Enemy_Citizen_Unhappy_Pct",
    "Irrigation_Pct", "Mining_Pct", "Output_Tile_Punish_Pct",
})

#: Он не смотрит на время и это прямо говорит (стр. 173): не оцениваем.
TIME_EFFECTS: frozenset[str] = frozenset({
    "Turn_Years", "Turn_Fragments", "Slow_Down_Timeline",
})


def content_value(amount: int, unhappy: float, entertainers: float,
                  num_cities: int, *, empire_size_base: float = 0.0,
                  empire_size_step: float = 0.0,
                  cities: int = 0) -> float:
    """`dai_content_effect_value` (стр. 77–111).

    `unhappy` — итоговое число недовольных (`feel[CITIZEN_UNHAPPY][FEELING_FINAL]`),
    `entertainers` — его `get_entertainers` (специалисты, дающие счастье).
    Ограничение нашего наблюдения: промежуточные ступени счастья стенд не публикует,
    поэтому `max_converted` берётся итоговым — как у него, когда ступени не ниже итога.
    """
    value = 0.0
    max_converted = float(unhappy)          # наш аналог MIN по ступеням (см. докстроку)
    value = min(float(amount), max_converted + float(entertainers)) * CONTENT_WEIGHT

    if num_cities > 1:
        factor = 2
        _cities = float(cities) if cities else float(num_cities)
        if _cities > float(empire_size_base):
            if float(empire_size_base) > 0:
                step = max(float(empire_size_step), 1.0)
                factor += int(_cities / step)
            factor += 2
        value += factor * num_cities * amount
    return value


def effect_value(effect: str, amount: int, *, c: int = 1, unhappy: float = 0.0,
                 entertainers: float = 0.0, units_supported: int = 0,
                 num_cities: int = 1, cities: int = 0,
                 empire_size_base: float = 0.0, empire_size_step: float = 0.0,
                 unhappy_free: bool = False) -> float:
    """`dai_effect_value` (стр. 138) для видов эффектов, которые мир действительно использует.

    `c` — число городов в радиусе (`num_cities` у него же); `unhappy_free` — результат
    `get_city_bonus(pcity, EFT_NO_UNHAPPY) > 0`, который снимает всю ветку счастья.
    """
    if amount == 0:
        # Он режет нулевые эффекты немедленно: «временное отключение эффекта в правилах».
        return 0.0
    if effect in COUNTED_IN_BASE_WANT:
        return 0.0
    if effect in TIME_EFFECTS:
        return 0.0

    if effect in ("City_Vision_Radius_Sq", "Unit_Vision_Radius_Sq"):
        # «Грубая оценка» его же словами: amount — сколько клеток откроется (стр. 208).
        return float(c * amount)
    if effect == "Incite_Cost_Pct":
        return float(c * amount / 100)
    if effect == "Make_Happy":
        value = (float(entertainers) + float(unhappy)) * MAKE_HAPPY_WEIGHT * amount
        if float(cities) > float(empire_size_base):
            value += c * amount                     # «сместить недовольство большого царства»
        return value + c * amount
    if effect == "No_Unhappy":
        return (float(entertainers) + float(unhappy)) * NO_UNHAPPY_WEIGHT
    if effect == "Force_Content":
        return content_value(amount, unhappy, entertainers, c,
                             empire_size_base=empire_size_base,
                             empire_size_step=empire_size_step, cities=cities)
    if effect == "Make_Content":
        if unhappy_free:
            return 0.0
        return content_value(amount, unhappy, entertainers, c,
                             empire_size_base=empire_size_base,
                             empire_size_step=empire_size_step, cities=cities)
    if effect == "Make_Content_Mil_Per":
        if unhappy_free:
            return 0.0
        value = min(float(unhappy) + float(entertainers), float(amount)) * MAKE_CONTENT_MIL_WEIGHT
        value += min(amount, MAKE_CONTENT_MIL_PER_CITY) * c
        return value
    if effect == "Make_Content_Mil":
        if unhappy_free:
            return 0.0
        value = float(unhappy) * amount * max(units_supported, 0) * 2
        value += c * max(amount + 2, 1)
        return value
    # Прочие виды эффектов его код обрабатывает, но классические правила их не используют;
    # неизвестный вид даёт ноль, а не выдуманное число (и это видно в отчёте: см. `UNKNOWN`).
    return 0.0


#: Виды эффектов, для которых порт ещё не имеет ветки — считаются нулём и перечисляются
#: вызывающим, чтобы пробел был виден, а не растворялся в сумме.
UNKNOWN: set[str] = set()


def type_options(effects: list[tuple[str, int, str, str, str]], target: str, *,
                 c: int = 1, unhappy: float = 0.0, entertainers: float = 0.0,
                 units_supported: int = 0, num_cities: int = 1, cities: int = 0,
                 empire_size_base: float = 0.0, empire_size_step: float = 0.0,
                 unhappy_free: bool = False) -> float:
    """Ценность типа: сумма ценностей ЕГО эффектов, адресованных этому типу.

    `effects` — таблица мира из `env/rules_costs.py::EFFECTS`
    (`(эффект, величина, род цели, имя цели, охват)`).
    """
    total = 0.0
    for effect, amount, _kind, name, _range in effects:
        if str(name) != str(target):
            continue
        value = effect_value(str(effect), int(amount), c=c, unhappy=unhappy,
                             entertainers=entertainers, units_supported=units_supported,
                             num_cities=num_cities, cities=cities,
                             empire_size_base=empire_size_base,
                             empire_size_step=empire_size_step, unhappy_free=unhappy_free)
        if value == 0.0:
            UNKNOWN.add(str(effect))
        total += value
    return total