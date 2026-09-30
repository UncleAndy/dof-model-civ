"""Модуль действий: решение → вызов среды + журнал (объявлено ↔ использовано).

Формат вызова среды измерен: действие — это `(контроллер, актор, имя)`, и в числовых секциях
(`unit`, `gov`, `dipl`) актор приходит числом, а в `tech`/`player` — строкой (`cur_player`,
`message`). Поэтому актор приводится к числу, если строка целиком цифровая.

Журнал нужен внешнему фальсификатору: он сравнивает, что путь **объявлял**, и что реально
**ушло** на сервер. Расхождение — сигнал, а не мелочь.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def to_env_action(step) -> tuple:
    """Шаг пути -> аргумент `env.step`."""
    actor: Any = step.actor
    if isinstance(actor, str) and actor.isdigit():
        actor = int(actor)
    return (step.ctrl, actor, step.action)


class Journal:
    """Журнал решений: протокол (Proof of Implementation) и сверка «объявлено ↔ использовано»."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.declared = 0
        self.used = 0
        self.empty_turns = 0

    def write(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def note(self, declared: Optional[tuple], used: Optional[tuple]) -> None:
        if declared is not None:
            self.declared += 1
        if used is not None:
            self.used += 1

    def counters(self) -> dict:
        return {"объявлено": self.declared, "исполнено": self.used,
                "пустых_ходов": self.empty_turns,
                "расхождение": self.declared - self.used}