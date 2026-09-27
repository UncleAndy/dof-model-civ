"""Кандидаты для прогноза: какие действия вообще существуют в этом состоянии.

Ключевое отличие от прежнего генератора: кандидат несёт **не только дельту**, но и
состояние, которое он создаёт. Именно так прогноз видит последствия.

Про движение — измеренный факт вместо прежней догадки. Раньше здесь стояло, что
`goto_N` не несёт координат и потому движение моделируется семейством. Отозвано
2026-09-27: `ActGoto` строит имя как `"goto_%i" % dir8`, а команда — `ORDER_MOVE` с
этим же dir8, то есть **шаг в направлении N** (0=СЗ…7=ЮВ). Цель вычислима
(`live.direction_target`), поэтому на живом пути каждый шаг несёт своё настоящее имя
(`goto_3`) и свою клетку. Семейство по `reach` остаётся только там, где меню действий
нет вовсе (синтетика в тестах) — и там оно честно называется верхней границей.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from . import transitions as tr
from .state import ForecastState


@dataclass
class Valuations:
    """Оценки, которые прогноз берёт из модели. Все — в шкале ядра (0…1].

    Внедряются функциями, поэтому сам прогноз не знает ни про CivRealm, ни про
    карту: его можно проверять синтетикой, без живого стенда.
    """

    #: клетки, достижимые юнитом за ход (включая нераскрытые — их ценность даст
    #: среднее по раскрытым, и именно это создаёт мотивацию к разведке)
    reach: Callable[[str], list[tuple[int, int]]]
    #: годится ли площадка под город (гейт по еде)
    site_viable: Callable[[tuple[int, int]], bool]
    #: DoF города размера 1 на площадке (шкала ядра)
    city_dof: Callable[[tuple[int, int]], float]
    #: id городов, которыми можно распоряжаться
    city_ids: Callable[[], list[str]]
    #: что может построить город: [(тип, DoF, ходов)]
    productions: Callable[[str], list[tuple[str, float, int]]]
    #: что можно исследовать: [(технология, DoF, ходов)]
    techs: Callable[[], list[tuple[str, float, int]]]
    #: работы на клетке: [(действие, ΔDoF, id города или None)]
    works: Callable[[tuple[int, int]], list[tuple[str, float, str | None]]]
    #: носитель ли населения (только ему основание и цена площадки)
    is_carrier: Callable[[str], bool]
    #: предложенные серверу шаги юнита: [(имя `goto_<dir8>`, клетка назначения)].
    #: Задаётся на живом пути, где есть меню действий. `None` — состояние без
    #: провода (синтетика в тестах): тогда движение берётся семейством по `reach`,
    #: и это ЧЕСТНО называется верхней границей. Отозвано 2026-09-27: раньше здесь
    #: стояло, что координат у `goto_N` нет вовсе; измерено по исходнику стенда,
    #: что `N` — это dir8, поэтому на живом пути шаг имеет ТОЧНУЮ цель.
    moves: Callable[[str], list[tuple[str, tuple[int, int]]]] | None = None
    #: что город может поставить из УЛУЧШЕНИЙ: [(имя, Δопций ГОРОДА, ходов)].
    #: Улучшение не создаёт сущность — оно растит опции того же города (иначе
    #: здание считалось бы живым и индекс рос бы дважды). Пустой список по
    #: умолчанию: семейство подключается там, где оно есть (живой провод).
    improvements: Callable[[str], list[tuple[str, float, int]]] = lambda _city: []
    #: ценность раскрытия клетки, в единицах индекса (разрыв Дженсена по
    #: измеренному разбросу ценностей клеток, `info.py`). Ноль для уже раскрытой
    #: клетки — разглядывать в ней нечего.
    info_gain: Callable[[tuple[int, int]], float] = lambda _tile: 0.0
    #: МОЖЕТ ли сервер это предложить прямо сейчас: (вид, сущность, имя) → bool.
    #: Обязательный фильтр, а не украшение: модель площадки не знает правил стенда
    #: (например `citymindist = 2` — город нельзя основать рядом с другим), и без
    #: этой проверки прогноз выбирает действия, которых сервер не предлагает.
    #: Урок живой: первый прогон 25 раз подряд выбрал `build_city` юниту, которому
    #: он недоступен, и сторона простояла весь матч.
    allowed: Callable[[str, str, str], bool] = lambda _kind, _actor, _name: True
    #: Решил ли этот актёр в ЭТОМ ходу. Правило «один актёр — одно решение за ход»
    #: (конвенция civrealm); без него прогноз, вызванный второй раз за тот же ход,
    #: предлагает ход уже решившему актёру, раннер его отбрасывает — и счётчики
    #: решений перестают соответствовать тому, что ушло на провод.
    excluded: Callable[[str, str], bool] = lambda _ctrl, _actor: False


@dataclass
class Candidate:
    """Кандидат: действие, его преемник и немедленный эффект."""

    action: tuple[str, str, str]     # (ctrl, actor, name) — как на проводе
    effect: tr.Effect
    kind: str = ""                   # move | found | produce | research | work
    score_hint: float = 0.0          # для порядка ветвления (не для решения)
    extra: dict = field(default_factory=dict)


def tile_value(tile: tuple[int, int], vals: Valuations, *, carrier: bool) -> float:
    """Ценность клетки для того, кто на неё встанет (шкала индекса).

    У носителя — логарифм опций города на площадке; у остальных — только цена
    раскрытия. Оба слагаемых в одной шкале, иначе сравнение клеток было бы
    сравнением опций с логарифмами.
    """
    score = 0.0
    if carrier and vals.site_viable(tile):
        dof = float(vals.city_dof(tile))
        if dof > 1.0:
            score += math.log(dof)
    score += float(vals.info_gain(tile))
    return score


def _best_destination(state: ForecastState, unit_id: str, vals: Valuations,
                      *, max_moves: int) -> tuple[tuple[int, int] | None, float, float]:
    """Лучшая достижимая клетка для юнита: (клетка, её ценность, ценность текущей).

    Движение «в никуда» ценности не имеет и кандидатом не становится (иначе агент
    ходил бы без причины). Это путь БЕЗ меню действий (см. `Valuations.moves`).
    """
    here = state.positions.get(unit_id)
    if here is None:
        return None, 0.0, 0.0
    carrier = bool(vals.is_carrier(unit_id))
    current = tile_value(here, vals, carrier=carrier)
    tiles = [t for t in vals.reach(unit_id) if (int(t[0]), int(t[1])) != here]
    if not tiles:
        return None, 0.0, current
    scored = sorted(((tile_value(t, vals, carrier=carrier), t) for t in tiles),
                    key=lambda kv: kv[0], reverse=True)
    best_value, best_tile = scored[0]
    return (int(best_tile[0]), int(best_tile[1])), best_value, current


def candidates(state: ForecastState, vals: Valuations, *,
               max_moves: int = 3) -> list[Candidate]:
    """Все действия, которые прогноз считает возможными в этом состоянии.

    Порядок ветвления задаётся `score_hint` (предварительная оценка), но решение
    принимает поиск по всей глубине — предварительная оценка не является вердиктом.
    """
    out: list[Candidate] = []

    # 1. Основание города: носитель стоит на годной площадке.
    for unit_id, pos in list(state.positions.items()):
        if not vals.is_carrier(unit_id):
            continue
        tile = (int(pos[0]), int(pos[1]))
        if not vals.site_viable(tile):
            continue
        effect = tr.found_city(state, unit_id, city_dof=float(vals.city_dof(tile)))
        out.append(Candidate(action=("unit", unit_id, "build_city"),
                             effect=effect, kind="found",
                             score_hint=effect.delta,
                             extra={"tile": tile}))

    # 2. Движение. На живом пути — ТОЧНЫЕ шаги: каждая предложенная сервером
    #    команда `goto_<dir8>` имеет вычисляемую цель, поэтому кандидат несёт своё
    #    имя и свою клетку (никакой подстановки «первой попавшейся» на проводе).
    #    Без меню (синтетика) — семейство по `reach`, и это верхняя граница.
    for unit_id in list(state.positions):
        here = state.positions.get(unit_id)
        carrier = bool(vals.is_carrier(unit_id))
        current = tile_value((int(here[0]), int(here[1])), vals, carrier=carrier) \
            if here is not None else 0.0
        steps = vals.moves(unit_id) if vals.moves is not None else []
        if steps:
            for name, target in steps:
                tile = (int(target[0]), int(target[1]))
                value = tile_value(tile, vals, carrier=carrier)
                # Ход стоит ценности только если преемник её даёт.
                if value <= current:
                    continue
                effect = tr.move(state, unit_id, tile,
                                 info_gain=float(vals.info_gain(tile)))
                out.append(Candidate(action=("unit", unit_id, name),
                                     effect=effect, kind="move",
                                     score_hint=value - current,
                                     extra={"tile": tile, "value": value,
                                            "direction": name}))
            continue
        tile, best_value, current = _best_destination(state, unit_id, vals,
                                                      max_moves=max_moves)
        if tile is None:
            continue
        # Ход стоит ценности только если преемник её даёт: нулевое движение не
        # предлагается — иначе агент «ходит» без причины.
        if best_value <= current:
            continue
        effect = tr.move(state, unit_id, tile,
                         info_gain=float(vals.info_gain(tile)))
        out.append(Candidate(action=("unit", unit_id, "goto"),
                             effect=effect, kind="move",
                             score_hint=best_value - current,
                             extra={"tile": tile, "value": best_value}))

    # 3. Производство: у города появляются будущие юниты.
    for city_id in vals.city_ids():
        if city_id not in state.dof:
            continue
        for unit_type, unit_dof, turns in vals.productions(city_id):
            effect = tr.produce(state, city_id,
                                unit_id=f"{city_id}:{unit_type}",
                                unit_dof=float(unit_dof), turns=int(turns))
            out.append(Candidate(action=("city", city_id, f"produce_{unit_type}"),
                                 effect=effect, kind="produce",
                                 score_hint=effect.delta,
                                 extra={"turns": turns, "type": unit_type}))

    # 4. Исследование: технология приносит открытый набор.
    for tech_id, tech_dof, turns in vals.techs():
        effect = tr.research(state, tech_id, tech_dof=float(tech_dof),
                             turns=int(turns))
        out.append(Candidate(action=("tech", "cur_player", tech_name(tech_id)),
                             effect=effect, kind="research",
                             score_hint=effect.delta, extra={"turns": turns}))

    # 4b. Улучшения: опции города растут, новой сущности не появляется.
    for city_id in vals.city_ids():
        if city_id not in state.dof:
            continue
        for name, gain, turns in vals.improvements(city_id):
            effect = tr.improve(state, city_id, gain=float(gain), turns=int(turns))
            out.append(Candidate(action=("city", city_id, f"produce_{name}"),
                                 effect=effect, kind="improve",
                                 score_hint=effect.delta,
                                 extra={"turns": turns, "type": name,
                                        "gain": gain}))

    # 5. Работы: измеренный эффект на клетке (нулевой остаётся нулевым кандидатом,
    #    но с нулевым вкладом — решение о нём принимает поиск, а не генератор).
    for unit_id, pos in list(state.positions.items()):
        for action, tile_delta, city_id in vals.works((int(pos[0]), int(pos[1]))):
            effect = tr.work(state, city_id=city_id,
                             tile_delta=float(tile_delta), action=action)
            out.append(Candidate(action=("unit", unit_id, action),
                                 effect=effect, kind="work",
                                 score_hint=effect.delta,
                                 extra={"city": city_id, "tile_delta": tile_delta}))

    # Обязательный фильтр: прогноз вправе выбирать только то, что сервер реально
    # предлагает. Правила стенда (например минимальная дистанция между городами)
    # модели площадки неизвестны — их знает провод.
    offered = [c for c in out
               if vals.allowed(c.kind, c.action[1], c.action[2])]
    # И только тем, кто в этом ходу ещё не решал: иначе предложение уйдёт актёру,
    # чей ход уже сделан, раннер его отбросит — а счётчики решений разойдутся с тем,
    # что реально ушло на провод (измерено: 61 «действие» при 31 отправленном).
    return [c for c in offered if not vals.excluded(c.action[0], c.action[1])]


def tech_name(tech_id: str) -> str:
    """`tech_12` → `research_tech_12`: имя действия на проводе."""
    return f"research_{tech_id}"
