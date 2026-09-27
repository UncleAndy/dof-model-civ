"""Кандидаты для прогноза: какие действия вообще существуют в этом состоянии.

Ключевое отличие от прежнего генератора: кандидат несёт **не только дельту**, но и
состояние, которое он создаёт. Именно так прогноз видит последствия.

Про движение — честное ограничение, и оно важное. `goto_N` в наблюдении не несёт
координат (параметры буквально `true`), поэтому «шагнуть на конкретную клетку»
назвать действием нельзя. Движение моделируется **семейством** с абстрактным
преемником: «носитель ушёл на лучшую достижимую клетку». Это **верхняя граница**
(мы предполагаем лучшую цель из доступных), и она согласуется с общей позицией
модели: она считает ПОТЕНЦИАЛ, а что выберет мир — его дело. Ограничение
называется прямо, а не прячется за формулой.
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


def _best_destination(state: ForecastState, unit_id: str, vals: Valuations,
                      *, max_moves: int) -> tuple[tuple[int, int] | None, float, float]:
    """Лучшая достижимая клетка для юнита: (клетка, её ценность, ценность текущей).

    Ценность клетки для носителя — логарифм опций города на ней (шкала индекса, в
    которой принимается решение); для не-носителя — только цена раскрытия. Оба
    слагаемых в одной шкале, иначе сравнение клеток было бы сравнением опций с
    логарифмами.

    Движение «в никуда» ценности не имеет и кандидатом не становится (иначе агент
    ходил бы без причины).
    """
    here = state.positions.get(unit_id)
    if here is None:
        return None, 0.0, 0.0
    carrier = bool(vals.is_carrier(unit_id))

    def value(tile: tuple[int, int]) -> float:
        score = 0.0
        if carrier and vals.site_viable(tile):
            dof = float(vals.city_dof(tile))
            if dof > 1.0:
                score += math.log(dof)
        score += float(vals.info_gain(tile))
        return score

    current = value(here)
    tiles = [t for t in vals.reach(unit_id) if (int(t[0]), int(t[1])) != here]
    if not tiles:
        return None, 0.0, current
    scored = sorted(((value(t), t) for t in tiles), key=lambda kv: kv[0], reverse=True)
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

    # 2. Движение: семейство с абстрактным преемником (см. docstring модуля).
    for unit_id in list(state.positions):
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
