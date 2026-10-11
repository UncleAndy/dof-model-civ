"""Прогноз: перебор вариантов с перевыводом возможностей и дисконтом за ход.

Отличие от прежнего поиска — в одном: на каждом уровне набор возможностей
**выводится заново** для состояния, которое создало предыдущее действие. Поэтому
поиск видит последствия («идти → встать на площадку → основать город»), а не
повторяет сегодняшнее меню.

Три правила, унаследованные от DOF-Core и не смягчённые здесь:

* **вето на коллапс** (Аксиома 3): ветвь, где обратимая сущность ушла в коллапс,
  отбрасывается;
* **штраф за необратимость** (Аксиома 4): у необратимого действия вычитается
  штраф, а не «поправка к привлекательности»;
* **строгое улучшение**: действие выбирается только если итоговое значение
  строго больше нуля; ноль означает «не действовать».

Порядок ветвления считается по **ценности преемника**, а не по немедленному
эффекту: иначе ход, у которого сейчас ноль, но который открывает основание города,
был бы срезан лучом до того, как это станет видно.
"""
from __future__ import annotations

import os

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .options import Candidate, Valuations, candidates
from .state import ForecastState

if TYPE_CHECKING:                       # только для аннотаций
    from .transitions import Effect

#: Дисконт за ход прогноза. Дальняя выгода весомее нуля, но меньше ближней:
#: при 0.8 цепочка из пяти шагов даёт 3.36, а не 5.
FORECAST_GAMMA = 0.8
#: Сколько кандидатов берётся в ветвление на каждом уровне.
FORECAST_BEAM = 3
#: Глубина прогноза в ходах.
FORECAST_HORIZON = 3
#: Штраф за необратимое действие (в шкале ядра) — аналог context-switch penalty.
IRREVERSIBLE_PENALTY = 0.05


@dataclass
class Choice:
    """Итог прогноза."""

    action: tuple[str, str, str] | None
    value: float
    path: list[tuple[str, str, str]] = field(default_factory=list)
    reason: str = ""
    nodes: int = 0
    best_candidate: Candidate | None = None
    #: состав кандидатов в исходном состоянии: {вид: сколько}. Без него «нет
    #: улучшения» неотличимо от «нет кандидатов» — а это разные факты: первый
    #: означает «всё, что есть, невыгодно», второй — «набор пуст, и это вопрос к
    #: проводнику ценностей, а не к поиску».
    candidate_kinds: dict[str, int] = field(default_factory=dict)


@dataclass
class _Node:
    state: ForecastState
    path: list[tuple[str, str, str]]
    value: float
    discount: float
    first: Candidate | None = None


def best_immediate(state: ForecastState, vals: Valuations, *,
                   max_moves: int = 3) -> float:
    """Лучший одношаговый выигрыш в состоянии — эвристика для порядка ветвления.

    Это НЕ вердикт: она только решает, какие ветви не срезать. Решение принимает
    полный перебор до горизонта по накопленной ценности.
    """
    best = 0.0
    for cand in candidates(state, vals, max_moves=max_moves):
        best = max(best, cand.effect.delta)
    return best


def _step_factor(effect: Effect, gamma: float) -> float:
    """Множитель времени шага: `time_factor`, если он задан, иначе `γ^delay`.

    Задаётся там, где «приходит через T ходов» не равно «полезно T ходов» —
    единственный такой случай в модели — постройка (§10.25.4).
    """
    if effect.time_factor is not None:
        return float(effect.time_factor)
    return gamma ** effect.delay


def _rank_key(cand: Candidate, state: ForecastState, vals: Valuations,
              discount: float, gamma: float, max_moves: int) -> float:
    """Порядок ветвления: немедленный эффект + дисконтированная ценность преемника."""
    successor_value = best_immediate(cand.effect.state, vals, max_moves=max_moves)
    return (cand.effect.delta
            + discount * _step_factor(cand.effect, gamma) * successor_value)


def choose(state: ForecastState, vals: Valuations, *,
           horizon: int = FORECAST_HORIZON,
           beam: int = FORECAST_BEAM,
           gamma: float = FORECAST_GAMMA,
           max_moves: int = 3,
           irreversible_penalty: float = IRREVERSIBLE_PENALTY,
           min_improvement: float = 0.0) -> Choice:
    """Выбрать первый шаг лучшей ветви прогноза.

    Возвращает `action=None`, если ни одна ветвь не даёт строгого улучшения —
    это законный исход (не действовать), а не сбой.
    """
    root = _Node(state=state, path=[], value=0.0, discount=1.0, first=None)
    frontier = [root]
    nodes = 0
    root_cands = candidates(state, vals, max_moves=max_moves)
    kinds: dict[str, int] = {}
    for cand in root_cands:
        kinds[cand.kind] = kinds.get(cand.kind, 0) + 1
    # Диагностика по требованию: чем правило меряет кандидатов в ЭТОМ ходу.
    # Включается переменной окружения, меры не меняет — только печатает.
    if os.environ.get("DOF_TRACE_CANDIDATES"):
        top = sorted(root_cands, key=lambda c: float(c.effect.delta),
                     reverse=True)[:8]
        print(f"        [кандидаты] всего {len(root_cands)}; сильнейшие:",
              flush=True)
        for cand in top:
            flag = "обратим" if cand.effect.reversible else "НЕОБРАТИМ"
            print(f"          {cand.kind:22s} дельта {float(cand.effect.delta):+.4f} "
                  f"{flag}  {cand.action}", flush=True)

    for _depth in range(max(1, horizon)):
        nxt: list[_Node] = []
        for node in frontier:
            cands = candidates(node.state, vals, max_moves=max_moves)
            if not cands:
                nxt.append(node)          # тупик: ветвь остаётся со своей ценностью
                continue
            ranked = sorted(
                cands,
                key=lambda c: _rank_key(c, node.state, vals, node.discount,
                                        gamma, max_moves),
                reverse=True,
            )[:max(1, beam)]
            for cand in ranked:
                nodes += 1
                successor = cand.effect.state
                if successor.collapsed():      # вето Аксиомы 3
                    continue
                penalty = 0.0 if cand.effect.reversible else irreversible_penalty
                gain = (cand.effect.delta - penalty) * _step_factor(cand.effect, gamma)
                nxt.append(_Node(
                    state=successor,
                    path=node.path + [cand.action],
                    value=node.value + node.discount * gain,
                    discount=node.discount * gamma,
                    first=node.first or cand,
                ))
        if not nxt:
            break
        frontier = nxt

    best = max(frontier, key=lambda n: n.value)
    composition = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "нет"
    if best.value <= min_improvement or best.first is None:
        return Choice(action=None, value=best.value, path=[],
                      reason=(f"нет строгого улучшения (лучшее значение "
                              f"{best.value:+.4f} ≤ {min_improvement:+.4f}; "
                              f"кандидаты: {composition})"),
                      nodes=nodes, best_candidate=best.first,
                      candidate_kinds=kinds)
    return Choice(action=best.first.action, value=best.value, path=best.path,
                  reason=f"улучшение {best.value:+.4f} по пути {len(best.path)} ход(ов)",
                  nodes=nodes, best_candidate=best.first,
                  candidate_kinds=kinds)
