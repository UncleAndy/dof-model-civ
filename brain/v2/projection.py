"""Проекция: переход «действие → состояние′» (отдельная система, решение 6.1).

ЧТО ЗДЕСЬ ЕСТЬ И ЧЕГО НЕТ. Проекция ничего не выдумывает: она читает **наблюдённые эффекты**
семейства действий из графа знаний (`knowledge.effects`) и по ним предсказывает, что изменится.
Пока эффект не наблюдался, проекция честно отвечает «неизвестно» — и это не пробел, а сигнал:
неизвестный переход надо добыть пробой (аксиома 5).

Отсюда порядок работы агента: сначала он не знает ничего и потому **исследует**; знание растёт,
проекция начинает предсказывать, и лишь тогда появляется чем торговать calculus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .knowledge import KnowledgeGraph


@dataclass
class Projection:
    """Что проекция говорит про один переход."""
    known: bool
    ctrl: str
    family: str
    changes: dict = field(default_factory=dict)      # измеренные изменения (накопленные)
    new_entities: dict = field(default_factory=dict)  # {"city": 1} — появление сущностей
    lost_entities: dict = field(default_factory=dict)
    knowledge_gain: int = 0                          # +1, если эффект ещё не наблюдался
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"known": self.known, "ctrl": self.ctrl, "family": self.family,
                "changes": self.changes, "new_entities": self.new_entities,
                "lost_entities": self.lost_entities, "knowledge_gain": self.knowledge_gain,
                "source": self.source}


def project(graph: KnowledgeGraph, ctrl: str, family: str) -> Projection:
    """Предсказание перехода по наблюдённому эффекту семейства."""
    rec = graph.effect_of(ctrl, family)
    if not rec:
        return Projection(known=False, ctrl=ctrl, family=family, knowledge_gain=1,
                          source="эффект семейства ещё не наблюдался")
    changes = dict(rec.get("change_counts") or {})
    new = {k[:-4]: v for k, v in changes.items() if k.endswith("_new") and v > 0}
    lost = {k[:-5]: v for k, v in changes.items() if k.endswith("_lost") and v > 0}
    return Projection(known=True, ctrl=ctrl, family=family, changes=changes,
                      new_entities=new, lost_entities=lost, knowledge_gain=0,
                      source=f"наблюдено {rec.get('seen', 0)} раз(а)")