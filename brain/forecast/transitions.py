"""Переходы: «действие → состояние после него».

Это то, чего не было в прежнем поиске. Там список кандидатов переиспользовался на
каждом уровне, поэтому последствий не существовало: идти к площадке не меняло
набор возможностей, и поиск не мог увидеть, что после хода появится основание
города.

Каждый переход возвращает НОВОЕ состояние и, если у действия есть немедленный
эффект, его величину в шкале ядра (приращение `Σ ln DoF`). Всё, что предсказать
нельзя честно (какие именно клетки раскроются за ход, что построит соперник), не
выдумывается: переход меняет только то, что следует из самого действия.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .state import EPSILON, ForecastState


@dataclass
class Effect:
    """Результат перехода: состояние и немедленное изменение индекса."""

    state: ForecastState
    delta: float
    delay: int = 0          # через сколько ходов появляется эффект (для дисконта)
    reversible: bool = True
    note: str = ""


def remove_entity(state: ForecastState, entity_id: str) -> float:
    """Убрать сущность и вернуть вклад её удаления в индекс (ln DoF)."""
    value = state.dof.pop(entity_id, 0.0)
    state.reversible.pop(entity_id, None)
    state.root_dof.pop(entity_id, None)
    state.collapse_sources.discard(entity_id)
    if value <= EPSILON:
        return 0.0
    return -math.log(max(value, EPSILON))


def add_entity(state: ForecastState, entity_id: str, dof: float, *,
               reversible: bool = True) -> float:
    """Добавить сущность и вернуть вклад её появления в индекс (ln DoF)."""
    value = max(0.0, float(dof))
    state.dof[entity_id] = value
    state.reversible[entity_id] = bool(reversible)
    state.root_dof[entity_id] = value
    if value <= EPSILON:
        return 0.0
    return math.log(max(value, EPSILON))


def index_delta(state: ForecastState, entity_id: str, delta: float) -> float:
    """Изменение индекса от прибавки `delta` к уже существующей сущности."""
    if delta == 0.0 or entity_id not in state.dof:
        return 0.0
    before = state.dof[entity_id]
    after = min(1.0, max(EPSILON, before + delta))
    state.dof[entity_id] = after
    return math.log(after) - math.log(max(before, EPSILON))


def move(state: ForecastState, unit_id: str, target: tuple[int, int]) -> Effect:
    """Ход юнита: меняется позиция и раскрытие клетки, куда он встал.

    Немедленного изменения индекса нет: ценность хода — в том, что станет
    доступно на новой клетке (площадка, основание города, информация). Именно
    поэтому цена хода не может считаться «дельтой действия»: её даёт преемник.

    Раскрытой считается только клетка, на которую юнит встал, — это достоверно.
    Остальное раскрытие за ход предсказать нельзя, и оно не приписывается.
    """
    new = state.clone()
    target = (int(target[0]), int(target[1]))
    new.positions[unit_id] = target
    new.revealed.add(target)
    return Effect(state=new, delta=0.0, delay=0, reversible=True,
                  note=f"ход {unit_id} → {target}")


def found_city(state: ForecastState, unit_id: str, *, city_id: str | None = None,
               city_dof: float = 0.0) -> Effect:
    """Основание города: носитель исчезает, появляется город.

    Немедленный эффект — разница индекса: с городом минус с носителем. До сих пор
    основание считалось действием с постоянной ценой, а не разницей, и знак этой
    разницы не был виден.
    """
    new = state.clone()
    pos = new.positions.pop(unit_id, None)
    if city_id is not None:
        cid = city_id
    elif pos is not None:
        cid = f"city_at_{pos[0]}_{pos[1]}"
    else:
        cid = f"city_from_{unit_id}"
    delta = remove_entity(new, unit_id)
    delta += add_entity(new, cid, float(city_dof), reversible=False)
    if pos is not None:
        new.cities[cid] = pos
    return Effect(state=new, delta=delta, delay=0, reversible=False,
                  note=f"основание города носителем {unit_id}")


def produce(state: ForecastState, city_id: str, *, unit_id: str,
            unit_dof: float, turns: int) -> Effect:
    """Производство: в городе через `turns` ходов появится юнит.

    Юнит добавляется в состояние сразу (его возможности принадлежат будущему), а
    задержка вынесена в `delay` — дисконт за неё применяет поиск. Иначе «через
    пять ходов» и «сейчас» весили бы одинаково.
    """
    new = state.clone()
    delta = add_entity(new, unit_id, float(unit_dof), reversible=True)
    return Effect(state=new, delta=delta, delay=max(0, int(turns)),
                  reversible=False, note=f"производство {unit_id} ({city_id}) "
                                         f"за {turns} ход(ов)")


def research(state: ForecastState, tech_id: str, *, tech_dof: float,
             turns: int = 0) -> Effect:
    """Исследование: появляется сущность технологии — её открытый набор.

    `turns` — за сколько ходов технология исследуется (задержка уходит в дисконт).
    """
    new = state.clone()
    delta = add_entity(new, tech_id, float(tech_dof), reversible=False)
    return Effect(state=new, delta=delta, delay=max(0, int(turns)),
                  reversible=False, note=f"исследование {tech_id}")


def work(state: ForecastState, *, city_id: str | None, tile_delta: float,
         action: str) -> Effect:
    """Работа: меняется выход клетки, а значит возможности того, кто её работает.

    Величина берётся ИЗМЕРЕННАЯ (таблица работ); нулевая остаётся нулевой —
    измеренный ноль это знание, а не повод подставить правдоподобное число.
    """
    new = state.clone()
    delta = 0.0
    if city_id is not None and city_id in new.dof:
        delta = index_delta(new, city_id, float(tile_delta))
    return Effect(state=new, delta=delta, delay=0, reversible=True,
                  note=f"работа {action}")
