"""Постоянное хранилище знаний агента.

Зачем: знание о мире добывает **сам агент** в пробных играх и складывает в свою базу, а не
человек замером со стороны (решение Andy, 2026-09-30). Поэтому хранилище:

* живёт на диске между партиями (`knowledge/world.json` по умолчанию);
* накапливает наборы возможностей, связи и счётчики наблюдений;
* выдаёт **открытые вопросы**, выведенные из графа, — их агент и идёт закрывать пробой;
* сохраняется после каждой партии (и по ходу — вызывающий решает).

Человек здесь только пишет механизм. Данные наполняет мир.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .knowledge import KnowledgeGraph, build_graph


class KnowledgeStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.graph = KnowledgeGraph.load(self.path) if self.path.exists() else KnowledgeGraph()
        self.games = self.graph.world.get("games", 0)

    # --- наблюдение ---
    def observe(self, obs: dict, available: dict, own_id: int = 0,
                turn: Optional[int] = None) -> KnowledgeGraph:
        """Влить одно наблюдение (ход) в базу. Возвращает обновлённый граф."""
        self.graph = build_graph(obs, available, own_id=own_id, prior=self.graph, turn=turn)
        return self.graph

    def end_game(self, save: bool = True) -> None:
        """Партия окончена: счётчик партий и запись на диск."""
        self.games += 1
        self.graph.world["games"] = self.games
        if save:
            self.save()

    def save(self) -> Path:
        """На диск уходит только постоянное знание: типы, технологии, словарь меню."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return self.graph.permanent_only().freeze(self.path)

    # --- что агент ещё не знает ---
    def unknowns(self) -> list[dict]:
        return self.graph.unknowns()

    def summary(self) -> dict[str, Any]:
        st = self.graph.stats()
        caps = {e.name: len(e.attrs.get("capabilities") or [])
                for e in self.graph.by_kind("unit_type") if e.attrs.get("capabilities")}
        return {"путь": str(self.path), "партий": self.games,
                "наблюдений": st["observations"], "сущностей": st["entities"],
                "связей": st["edges"], "наборы_возможностей": caps,
                "открытых_вопросов": len(self.unknowns())}

    def report(self, limit: int = 12) -> str:
        s = self.summary()
        lines = [f"база знаний: {s['путь']}",
                 f"  партий: {s['партий']}, наблюдений: {s['наблюдений']}, "
                 f"сущностей: {s['сущностей']}, связей: {s['связей']}",
                 f"  наборы возможностей типов: {s['наборы_возможностей']}",
                 f"  открытых вопросов: {s['открытых_вопросов']}"]
        for u in self.unknowns()[:limit]:
            lines.append(f"    · {u['eid']} — {u['why']} (проба: {u['probe']})")
        return "\n".join(lines)


def default_store_path(project_root: str | Path) -> Path:
    """Путь базы знаний по умолчанию — внутри проекта, рядом с моделью."""
    return Path(project_root) / "knowledge" / "world.json"