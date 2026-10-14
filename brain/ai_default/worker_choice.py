"""Выбор работы рабочим — перенос встроенного ИИ, а не наша выдумка.

Источник (закреплённый коммит `14b7a645a74155d4f3dd300221c5b4f0ffca8fe8`):

* `consider_settler_action` — `server/advisors/autoworkers.c:308`;
* обход клеток и работ — `settler_evaluate_improvements`, `autoworkers.c:439` (тело
  468–579): каждая клетка радиуса города, `oldv = city_tile_value(...)`;
* `WORKER_FACTOR` — `autoworkers.c:70` (1024, множитель против ошибок округления);
* оценка ценности клетки — `brain.ai_default.values.city_tile_value`
  (`infracache.c:293`).

Зачем перенос. У нас работу клетки выбирал СЧЁТ СОВПАДЕНИЙ со списком предпочтений
(`_preference_score`), а не ценность клетки для города. Замер (`/tmp/dof_growth.log`):
город стоял на размере 1 при излишке еды 0, потому что выбирались шахта и дорога вместо
того, что поднимет еду с 2 до 3.

Что перенесено буквально:

* условие «улучшает ли работа клетку»: `improves = new > old` либо `new == old and extra > 0`;
* при равной ценности предпочитается клетка с БОЛЬШЕЙ старой ценностью
  (`old_tile_value > *best_old_tile_value`) — то есть уже хорошая клетка;
* клетка, которая не обрабатывается городом (`in_use == False`), делит выигрыш на 2;
* выигрыш амортизируется по числу ходов: `amortize(total, delay)`;
* работа с нулевой выгодой не выбирается НИКОГДА (`best_newv = 0` в исходнике).

Что НЕ перенесено и почему (прямой перенос невозможен):

* поиск пути (`pf_map`, `pos.turn`, `pos.moves_left`) — у нас нет карты проходимости
  в его виде; запаздывание передаёт вызывающий;
* `unit_list_iterate` (чужие рабочие на клетке) и `adv_settler_safe_tile` — их нет в
  нашем наблюдении; передаются вызывающим как готовый признак;
* `aw_transform_action_iterate` — перебор возможных работ из правил мира; у нас
  перебирает вызывающий.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from brain.ai_default.values import city_tile_value

#: `autoworkers.c:70` — множитель против ошибок округления (при сравнении сокращается).
WORKER_FACTOR: int = 1024


@dataclass(frozen=True)
class WorkChoice:
    """Лучшая найденная работа. Поля — как у `best_*` в `consider_settler_action`."""

    activity: str
    tile: tuple[int, int] | None
    value: float
    old_value: float
    extra: float
    delay: int
    improves_worked: bool


def consider_settler_action(activity: str, *, new_tile_value: float, old_tile_value: float,
                            in_use: bool, delay: int, best: WorkChoice,
                            extra: float = 0.0, tile: tuple[int, int] | None = None
                            ) -> WorkChoice:
    """Сравнить работу `activity` с лучшей известной — `autoworkers.c:308`, строка в строку.

    «Compares the best known tile improvement action with improving ptile with activity act.
    Calculates the value of improving the tile by discounting the total value by the time it
    would take to do the work and multiplying by some factor.»
    """
    if extra < 0:
        extra = 0.0

    if new_tile_value > old_tile_value:
        improves = True
    elif new_tile_value == old_tile_value and extra > 0:
        improves = True
    else:
        improves = False

    # find the present value of the future benefit of this action
    if improves or extra > 0:
        if not best.improves_worked and not in_use:
            # Going to improve tile that is not yet in use.
            # Getting the best possible total for next citizen to work on is more
            # important than amount tile gets improved.
            if improves and (new_tile_value > best.value
                             or (new_tile_value == best.value
                                 and old_tile_value < best.old_value)):
                return WorkChoice(activity, tile, new_tile_value, old_tile_value, extra,
                                  delay, False)
            return best

        # At least one of the previous best or current tile is in use.
        # Prefer the tile that gets improved more, regardless of the resulting total.
        base_value = new_tile_value - old_tile_value
        total_value = base_value * WORKER_FACTOR
        if not in_use:
            total_value /= 2
        total_value += extra * WORKER_FACTOR

        # use factor to prevent rounding errors
        total_value = amortize(total_value, delay)

        if best.improves_worked:
            old_improvement_value = best.value
        else:
            # Convert old best_value to improvement value compatible with in_use tile value
            old_improvement_value = amortize(
                (best.value - best.old_value) * WORKER_FACTOR / 2, best.delay)

        if (total_value > old_improvement_value
                or (total_value == old_improvement_value
                    and old_tile_value > best.old_value)):
            if in_use:
                return WorkChoice(activity, tile, total_value, old_tile_value, extra,
                                  delay, True)
            return WorkChoice(activity, tile, new_tile_value, old_tile_value, extra,
                              delay, False)
    return best


def amortize(benefit: float, delay: int) -> float:
    """`server/advisors/advtools.c:29` при `MORT 24` (`advtools.h:19`).

    Взят из слоя переноса, чтобы формула жила в одном месте.
    """
    from brain.ai_default.values import amortize as _amortize

    return _amortize(benefit, delay)


def empty_choice() -> WorkChoice:
    """Начальное «лучшее» — как в исходнике: `best_newv = 0`, `best_oldv = 9999`.

    Ноль как начальная ценность — это не мелочь: он гарантирует, что работа, которая
    НИЧЕГО не улучшает, не будет выбрана.
    """
    return WorkChoice("", None, 0.0, 9999, 0.0, 0, False)


def choose_tile_work(tiles, *, in_use_tiles: frozenset = frozenset()) -> WorkChoice:
    """Выбрать работу: `settler_evaluate_improvements`, `autoworkers.c:439` (тело 468–579).

    ``tiles`` — последовательность ``(координата, старая тройка выходов,
    {имя_работы: новая тройка выходов, запаздывание})``. Выходы — ``(food, shield, trade)``.

    Почему новая ценность приходит готовой, а не считается здесь: в исходнике её даёт кэш
    (`initialize_infrastructure_cache`, `infracache.c:242`), который строит ВИРТУАЛЬНУЮ
    клетку после перехода рельефа (`adv_calc_plant`/`adv_calc_cultivate`) и зовёт
    `city_tile_value`. Переходы рельефа у нас уже собраны (`env/terrain_work_effects.py`),
    поэтому вызывающий считает по ним — а это ядро портируется отдельно и дословно.
    """
    best = empty_choice()
    for tile, old_outputs, works in tiles:
        old_value = city_tile_value(*old_outputs)
        in_use = tile in in_use_tiles
        for activity, (new_outputs, delay) in works.items():
            new_value = city_tile_value(*new_outputs)
            best = consider_settler_action(
                activity, new_tile_value=new_value, old_tile_value=old_value,
                in_use=in_use, delay=delay, best=best, tile=tile)
    return best

#: Работа → поле правил, которым выражен её прирост, и статья выхода, которую оно двигает.
WORK_INCREMENT_FIELDS: dict[str, tuple[str, int]] = {
    "mine": ("mining_shield_incr", 1),          # индекс 1 — щиты в тройке (food, shield, trade)
    "irrigation": ("irrigation_food_incr", 0),  # индекс 0 — еда
}


#: Работы дорожного рода → ключ в `ROAD_EFFECTS`; доля берётся у террейна.
#: Связка подтверждена САМИМИ правилами: `road_trade_incr_pct = percent of road trade_incr
#: applied to this terrain` (terrain.ruleset:119). Раньше дороги были исключены, пока связка
#: не проверена: торговля в его весах стоит 18, то есть дороже щитов (17), и включать её
#: наугад было нельзя.
ROAD_WORK_NAMES: dict[str, str] = {
    "road": "road",
    "build_road": "road",
    "railroad": "railroad",
    "build_railroad": "railroad",
}


def road_option_from_rules(terrain: str, outputs, work: str):
    """Вариант дорожной работы: `(новая тройка выходов, срок)` или None.

    Прирост = собственный прирост экстры (`ROAD_EFFECTS`) в доле, заданной ТЕРРЕЙНОМ
    (`road_trade_incr_pct` / `road_shield_incr_pct`). Ноль в правилах означает «дорога здесь
    ничего не даёт» — тогда работы не предлагаем, чтобы не тратить ходы впустую.
    """
    from env.terrain_work_effects import ROAD_EFFECTS, TERRAIN_WORK_EFFECTS
    from env.terrain_work_times import TERRAIN_WORK_TIMES

    key = str(terrain or "").strip().lower().replace(" ", "_")
    road_key = ROAD_WORK_NAMES.get(str(work))
    if road_key is None:
        return None
    times = TERRAIN_WORK_TIMES.get(key, {}) or {}
    if road_key not in times:
        return None
    effects = TERRAIN_WORK_EFFECTS.get(key, {}) or {}
    pct = float(effects.get(ROAD_PCT_FIELD.get(road_key, ""), 0.0) or 0.0)
    if pct == 0.0:
        return None
    own = ROAD_EFFECTS.get(road_key, {}) or {}
    new_outputs = list(outputs)
    changed = False
    for field, index in (("trade_incr", 2), ("shield_incr", 1), ("food_incr", 0),
                         ("trade_incr_const", 2), ("shield_bonus", 1)):
        if field not in own:
            continue
        gain = float(own[field]) * (pct / 100.0)
        if gain == 0.0:
            continue
        new_outputs[index] = new_outputs[index] + gain
        changed = True
    if not changed:
        return None
    return tuple(new_outputs), int(times[road_key])


#: Ключ процента по дорожному роду.
ROAD_PCT_FIELD: dict[str, str] = {
    "road": "road_trade_incr_pct",
    "railroad": "road_shield_incr_pct",
}


def work_options_from_rules(terrain: str, outputs, offered) -> dict:
    """Варианты работ для клетки: `{работа: (новая тройка выходов, срок)}` — из правил мира.

    Вход: террейн клетки, её текущие выходы `(food, shield, trade)` и имена работ, которые
    стенд СЕЙЧАС предлагает. Выход — только те работы, у которых в правилах есть прирост и
    есть срок: «нельзя» никогда не выглядит как «мгновенно».

    Срок берётся из правил террейна (`env/terrain_work_times.py`), потому что перенесённое
    правило встроенного ИИ дисконтирует выигрыш по числу ходов: `amortize(total, delay)`.
    """
    from env.terrain_work_effects import TERRAIN_WORK_EFFECTS
    from env.terrain_work_times import TERRAIN_WORK_TIMES

    effects = TERRAIN_WORK_EFFECTS.get(str(terrain), {}) or {}
    times = TERRAIN_WORK_TIMES.get(str(terrain), {}) or {}
    out: dict = {}
    for work in offered:
        name = str(work)
        if name in ROAD_WORK_NAMES:
            road = road_option_from_rules(terrain, outputs, name)
            if road is not None:
                out[name] = road
            continue
        field = WORK_INCREMENT_FIELDS.get(name)
        if field is None:
            continue
        key, index = field
        if key not in effects or name not in times:
            continue
        delta = float(effects[key])
        if delta == 0:
            continue
        new_outputs = list(outputs)
        new_outputs[index] = new_outputs[index] + delta
        out[name] = (tuple(new_outputs), int(times[name]))
    return out
