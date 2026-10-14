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


#: Число НАШИХ городов в радиусе эффекта — его таблица (`daicity.c:1648-1668`), не догадка:
#:   `cities[REQ_RANGE_CITY] = cities[REQ_RANGE_LOCAL] = 1`
#:   `cities[REQ_RANGE_PLAYER] = cities[WORLD/ALLIANCE/TEAM] = city_list_size(pplayer->cities)`
#:   `cities[REQ_RANGE_TILE/CADJACENT/ADJACENT] = 0`  («неверный радиус» для построек)
#:   `cities[REQ_RANGE_CONTINENT]` — города НА ТОМ континенте: у нас такого счёта нет.
#:
#: В `dai_effect_value` этот счёт приходит параметром `c` («given the number of cities in range
#: (c)», его же строка 136). Наш порт передавал `c=1` ВСЕГДА — верно для города, но эффекты
#: радиуса «Player»/«World» (85 строк из 270 в нашей таблице) от этого занижались в число
#: городов раз.
CITY_RANGE_ONE = ("", "local", "city", "traderoute")
CITY_RANGE_MINE = ("player", "world", "team", "alliance")
CITY_RANGE_NONE = ("tile", "cadjacent", "adjacent")


def cities_in_range(range_name, cities: int) -> int:
    """Сколько НАШИХ городов попадает под эффект этого радиуса.

    Неизвестный радиус (в том числе `continent`, для которого у нас нет счёта по континентам)
    даёт 1 и попадает в `NOTES` — незнание нельзя выдавать за ноль, но и выдумывать число
    городов тоже нельзя.
    """
    name = str(range_name or "").strip().lower()
    if name in CITY_RANGE_ONE:
        return 1
    if name in CITY_RANGE_MINE:
        return max(1, int(cities or 1))
    if name in CITY_RANGE_NONE:
        return 0
    NOTES.append(f"радиус эффекта «{range_name}» нам неизвестен: считаю как один город")
    return 1


def effect_value(effect: str, amount: int, *, c: int = 1, unhappy: float = 0.0,
                 entertainers: float = 0.0, units_supported: int = 0, affected: int = 0,
                 num_cities: int = 1, cities: int = 0,
                 empire_size_base: float = 0.0, empire_size_step: float = 0.0,
                 unhappy_free: bool = False, surplus_food: float = 0.0,
                 granary_size: float = 0.0) -> float:
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
    # Его военные семьи (`daieffects.c:441-460`). Именно через них ценна постройка
    # `Barracks`: у неё нет своих эффектов, она включает эти. Числа — его:
    # `num` — затронутые наши юниты (`affected_units` выше).
    if effect in ("HP_Regen", "HP_Regen_2"):
        return 5.0 * c + affected
    if effect == "Min_HP_Pct":
        return 3.0 * c + affected
    if effect == "Veteran_Combat":
        return 2.0 * c + affected
    if effect == "Veteran_Build":
        return float(amount) * (3.0 * c + affected)
    # §13.337: ветви, которых у нас не было вовсе, а мир их использует. Его код, буквально
    # (`daieffects.c:301`, `:305`):
    #   case EFT_SHRINK_FOOD:
    #     v += c * 4 + (amount / 15) * MAX(-pcity->surplus[O_FOOD], 1);
    #   case EFT_POPCOST_FREE:
    #     v += amount * city_granary_size(pcity->size) / 10;
    # Целочисленное деление — как в C: сначала произведение, потом деление.
    # Именно здесь живёт ценность `Granary` (её эффект — `Shrink_Food`), а житница — рычаг
    # роста, который по составу §13.333 отстаёт у нас в 48 раз.
    if effect == "Shrink_Food":
        return float(c * 4 + (int(amount) // 15) * max(-float(surplus_food), 1.0))
    if effect == "Popcost_Free":
        return float(int(amount) * int(granary_size) // 10)
    # Прочие виды эффектов его код обрабатывает, но классические правила их не используют;
    # неизвестный вид даёт ноль, а не выдуманное число (и это видно в отчёте: см. `UNKNOWN`).
    return 0.0


#: Замечания оценки (почему слагаемое пропущено) — для отчёта, а не для тишины.
NOTES: list[str] = []


#: Виды эффектов, для которых порт ещё не имеет ветки — считаются нулём и перечисляются
#: вызывающим, чтобы пробел был виден, а не растворялся в сумме.
UNKNOWN: set[str] = set()


def _holds(name: str, kind: str, held: frozenset[str]) -> bool:
    """Выполнено ли одно требование эффекта.

    Требование может быть названо ПОСТРОЙКОЙ (`Building Oracle`, `Tech Mysticism`) — тогда
    оно выполнено, если имя есть у города/игрока. Но бывает и ФЛАГОМ
    (`BuildingFlag Barracks`): измерено на правилах мира — у `Barracks` нет собственных
    эффектов, он только включает чужие через этот флаг, поэтому «держим ли мы флаг»
    проверяется по флагам удерживаемых построек, а не по имени.
    """
    if name in held:
        return True
    if str(kind) != "BuildingFlag":
        return False
    for building in held:
        row = BUILDING_COST.get(building) or {}
        if name in tuple(row.get("flags") or ()):
            return True
    return False


def affected_units(unit_reqs: tuple, units) -> int:
    """`num_affected_units` (стр. 120): сколько НАШИХ юнитов эффект затрагивает.

    Он идёт по КЛАССАМ юнитов и складывает `adv->stats.units.byclass[класс]` для классов,
    удовлетворяющих требованиям эффекта. Мы идём по нашим юнитам и проверяем ту же пару
    (класс, флаги) по каждому: `UnitClass Land` — класс совпадает, `UnitFlag NonMil FALSE` —
    у типа этого флага НЕТ.

    Названное расхождение: его проверка по классам может оказаться грубее (например, считать
    все наземные, включая невоенных), и тогда его число будет больше нашего. Это не подгонка,
    а известная разница: она видна и проверяема, потому что `byclass` — его собственный счётчик.
    """
    total = 0
    for unit in units or ():
        class_name, flags = (unit if isinstance(unit, (tuple, list)) and len(unit) >= 2
                             else (unit, ()))
        flags = tuple(flags or ())
        ok = True
        for requirement in unit_reqs or ():
            if not isinstance(requirement, (tuple, list)) or len(requirement) < 2:
                continue
            name, kind = str(requirement[0]), str(requirement[1])
            present = True
            if len(requirement) >= 3 and str(requirement[2]).upper() in ("TRUE", "FALSE"):
                present = str(requirement[2]).upper() == "TRUE"
            if kind == "UnitClass":
                hit = str(class_name) == name
            elif kind == "UnitFlag":
                hit = name in flags
            else:
                continue
            if hit != present:
                ok = False
                break
        if ok:
            total += 1
    return total


def requirements_met(row: tuple, held: frozenset[str]) -> bool:
    """Выполнены ли требования эффекта, кроме самого адресата.

    У `[effect_oracle]` эффект делает Храм счастливым, но требует ещё и `Oracle`; без этой
    проверки ценность Храма завышалась (измерено на правилах мира: три раздела
    `Make_Content`, из них один — про Оракула, другой — про `Mysticism`).
    """
    if len(row) < 8:
        return True
    for requirement in row[7] or ():
        if isinstance(requirement, (tuple, list)) and len(requirement) >= 2:
            name, kind = str(requirement[0]), str(requirement[1])
        else:
            name, kind = str(requirement), ""
        if not _holds(name, kind, held):
            return False
    return True


def type_options(effects: list[tuple], target: str, *,
                 held: frozenset[str] = frozenset(),
                 c: int = 1, unhappy: float = 0.0, entertainers: float = 0.0,
                 units_supported: int = 0, num_cities: int = 1, cities: int = 0,
                 empire_size_base: float = 0.0, empire_size_step: float = 0.0,
                 unhappy_free: bool = False, units=()) -> float:
    """Ценность типа: сумма ценностей ЕГО эффектов, адресованных этому типу.

    `effects` — таблица мира из `env/rules_costs.py::EFFECTS`
    (`(эффект, величина, род цели, имя цели, охват)`).
    """
    total = 0.0
    for row in effects:
        effect, amount, name = row[0], row[1], row[3]
        if str(name) != str(target):
            continue
        if not requirements_met(row, held):
            continue
        # Требования К ЮНИТАМ у его эффектов — это не «что должно быть у города», а
        # «на кого эффект действует»: их считает `num_affected_units` (стр. 120). Без этого
        # у `Barracks` (ветеранство и восстановление войск) ценность выходила нулевой.
        unit_reqs = row[8] if len(row) > 8 else ()
        affected = affected_units(unit_reqs, units) if unit_reqs else 0
        value = effect_value(str(effect), int(amount), c=c, unhappy=unhappy,
                             entertainers=entertainers, units_supported=units_supported,
                             affected=affected,
                             num_cities=num_cities, cities=cities,
                             empire_size_base=empire_size_base,
                             empire_size_step=empire_size_step, unhappy_free=unhappy_free)
        if value == 0.0:
            UNKNOWN.add(str(effect))
        total += value
    return total


# ── ЕГО ПРИОРИТЕТЫ ВЫХОДОВ (`server/advisors/advdata.c:492-512`) ─────────────────
#: «Никогда не ставьте нули: веса обычно умножаются на эти значения» — его же слова.
FOOD_PRIORITY = 30.0          # advdata.c:499 = FOOD_WEIGHTING (advbuilding.h)
SHIELD_PRIORITY = 17.0        # advdata.c:500 = SHIELD_WEIGHTING
SCIENCE_PRIORITY = 18.0 * 1.2  # advdata.c:503 = TRADE_WEIGHTING * 1.2
LUXURY_PRIORITY_SCIENCE = 1.0  # advdata.c:502 (ветка «царство хочет науку»)
LUXURY_PRIORITY_OTHER = 18.0   # advdata.c:505 (иначе роскошь тянет как торговля)
SCIENCE_PRIORITY_OTHER = 1.0   # advdata.c:506
GOLD_PRIORITY = 18.0          # advdata.c:508 = TRADE_WEIGHTING
POLLUTION_PRIORITY = 20.0     # advdata.c:512 = POLLUTION_WEIGHTING
HAPPY_PRIORITY = 1.0          # advdata.c:509
UNHAPPY_PRIORITY = 18.0       # advdata.c:510 («опасность»)
ANGRY_PRIORITY = 54.0         # advdata.c:511 («серьёзная опасность»)
INFRA_PRIORITY = 13.5         # advdata.c:513 = INFRA_WEIGHTING = TRADE_WEIGHTING * 0.75


def city_want(*, food: float, shields: float, science: float, gold: float,
              luxury: float = 0.0, pollution: float = 0.0, tax_rate: float | None = None,
              wants_science: bool = True) -> float:
    """`dai_city_want` (`daicity.c:1496`) — хотение города по его весам.

    Формула его, слагаемое в слагаемое:
        еда × 30
        щиты × 17 − загрязнение × 20   (только если щиты не нулевые)
        роскошь × приоритет
        наука × приоритет
        золото × 18                    (при налоге > 50 — ещё × (налог − 40) / 14)

    Приоритеты роскоши и науки зависят от его же ветки «царство хочет науку»
    (`adv_wants_science`, `advdata.c:501`), поэтому они в параметре, а не в константе.
    """
    luxury_priority = LUXURY_PRIORITY_SCIENCE if wants_science else LUXURY_PRIORITY_OTHER
    science_priority = SCIENCE_PRIORITY if wants_science else SCIENCE_PRIORITY_OTHER

    want = float(food) * FOOD_PRIORITY
    if float(shields) != 0.0:
        want += float(shields) * SHIELD_PRIORITY - float(pollution) * POLLUTION_PRIORITY
    want += float(luxury) * luxury_priority
    want += float(science) * science_priority
    if tax_rate is not None and float(tax_rate) > 50.0:
        want += float(gold) * GOLD_PRIORITY * (float(tax_rate) - 40.0) / 14.0
    else:
        want += float(gold) * GOLD_PRIORITY
    return want


#: Семантика видов прироста — из `common/effects.h` (строки 48-56), не моя догадка:
#:   Output_Add_Tile  — «добавить к КАЖДОЙ обрабатываемой клетке» (абсолют)
#:   Output_Inc_Tile  — «добавить к каждой обрабатываемой клетке, где выход уже есть»
#:   Output_Per_Tile  — «увеличить выход клетки на данный процент»
#:   Output_Bonus     — процентный бонус к выходу города (он складывает их в
#:                      `get_final_city_output_bonus`, `daicity.c:1459`)
OUTPUT_PRIORITY: dict[str, str] = {
    "Food": "food", "Shield": "shields", "Trade": "trade",
    "Science": "science", "Gold": "gold", "Luxury": "luxury",
}


def output_delta(effects: list[tuple], target: str, *, prod: dict[str, float],
                 worked_tiles: int) -> dict[str, float]:
    """Прирост выходов от эффектов типа — по его семантике (`common/effects.h`).

    `prod` — выходы города по видам (еда/щиты/торговля/наука/золото/роскошь). Значения
    `Output_Per_Tile` и `Output_Bonus` — проценты, `Output_Add_Tile` — абсолют на клетку.
    Виды, для которых нужен замер, которого у нас нет (`Output_Inc_Tile` — нужен выход
    каждой клетки, `Output_Waste_*`, `Pollu_*`), в прирост не входят и попадают в `UNKNOWN`.
    """
    delta: dict[str, float] = {}
    for row in effects:
        if len(row) < 6:
            continue
        effect, amount, _kind, name, _range, output_kind = row[0], row[1], row[2], row[3], row[4], row[5]
        if str(name) != str(target) or not output_kind:
            continue
        field = OUTPUT_PRIORITY.get(str(output_kind))
        if field is None:
            continue
        if effect == "Output_Bonus":
            delta[field] = delta.get(field, 0.0) + float(prod.get(field, 0.0)) * amount / 100.0
        elif effect == "Output_Per_Tile":
            # «увеличить выход клетки на N%»: суммарно — тот же процент от выхода города
            delta[field] = delta.get(field, 0.0) + float(prod.get(field, 0.0)) * amount / 100.0
        elif effect == "Output_Add_Tile":
            delta[field] = delta.get(field, 0.0) + float(amount) * max(0, int(worked_tiles))
        else:
            UNKNOWN.add(str(effect))
    return delta


def improvement_value(effects: list[tuple], target: str, *, prod: dict[str, float],
                      worked_tiles: int = 0, unhappy: float = 0.0,
                      entertainers: float = 0.0, units_supported: int = 0,
                      num_cities: int = 1, cities: int = 0,
                      empire_size_base: float = 0.0, empire_size_step: float = 0.0,
                      unhappy_free: bool = False, tax_rate: float | None = None,
                      wants_science: bool = True,
                      trade_split: tuple[float, float, float] | None = None,
                      held: frozenset[str] = frozenset(),
                      units=(), surplus_food: float = 0.0,
                      granary_size: float = 0.0) -> float:
    """Ценность улучшения: прирост хотения города плюс ценность эффектов счастья.

    Ровно так его `base_want` (`daicity.c:1495`) и устроен: «добавить постройку и сравнить
    хотение города» (`dai_city_want`), а эффекты счастья он считает отдельно
    (`dai_effect_value`). Обе половины — его.
    """
    effects = [row for row in effects if requirements_met(row, held)]
    delta = output_delta(effects, target, prod=prod, worked_tiles=worked_tiles)
    # ТОРГОВЛЯ у него не слагаемое: `dai_city_want` суммирует науку, золото и роскошь, а
    # торговля делится между ними ставками. Ставки берём из самого города (отношения
    # наблюдённых `science`/`prod_gold`/`luxury` к `prod_trade`), а не выдумываем; если их
    # взять неоткуда — прирост торговли не засчитываем (и это видно в отчёте, а не в сумме).
    if delta.get("trade"):
        rates = trade_split
        if not rates:
            trade_amount = delta.pop("trade")
            rendered_true = f"торговля +{trade_amount:.2f}"
            NOTES.append(f"прирост торговли у «{target}» не оценён: нет ставок города "
                         f"({rendered_true})")
        else:
            sci_rate, gold_rate, lux_rate = rates
            trade_amount = delta.pop("trade")
            delta["science"] = delta.get("science", 0.0) + trade_amount * sci_rate
            delta["gold"] = delta.get("gold", 0.0) + trade_amount * gold_rate
            delta["luxury"] = delta.get("luxury", 0.0) + trade_amount * lux_rate
    base = city_want(food=delta.get("food", 0.0), shields=delta.get("shields", 0.0),
                     science=delta.get("science", 0.0), gold=delta.get("gold", 0.0),
                     luxury=delta.get("luxury", 0.0), tax_rate=tax_rate,
                     wants_science=wants_science)
    content = 0.0
    for row in effects:
        if len(row) < 6 or str(row[3]) != str(target):
            continue
        # Требования К ЮНИТАМ — «на кого эффект действует» (`num_affected_units`, стр. 120):
        # без них постройка `Barracks` (ветеранство и восстановление войск) выходила нулём,
        # хотя у города уже стоят военные, ровно на которых она и работает.
        unit_reqs = row[8] if len(row) > 8 else ()
        # §13.313: `c` — ЧИСЛО НАШИХ ГОРОДОВ В РАДИУСЕ по его таблице, а не всегда единица.
        # Радиус строки лежит у нас в `row[4]` (тот же, что читает `output_delta`).
        content += effect_value(str(row[0]), int(row[1]),
                               c=cities_in_range(row[4] if len(row) > 4 else "", cities),
                               unhappy=unhappy,
                               entertainers=entertainers, units_supported=units_supported,
                               affected=affected_units(unit_reqs, units) if unit_reqs else 0,
                               num_cities=max(1, num_cities), cities=cities,
                               empire_size_base=empire_size_base,
                               empire_size_step=empire_size_step, unhappy_free=unhappy_free,
                               surplus_food=surplus_food, granary_size=granary_size)
    return base + content
