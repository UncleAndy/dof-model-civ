"""Общая защита тестов от записи в рабочие файлы проекта.

Зачем это здесь, а не в отдельных тестах. Юнит-тесты гоняют настоящий
`GameStateExtractor`, а он пишет сверки площадок в корпус. Первый прогон новой
сюиты добавил в рабочий `site_outcomes.jsonl` две строки, которых там быть не
должно: одна из них была записана ещё и с прежней (битой) сигнатурой — то есть
по корпусу нельзя было бы понять, тестовый это город или живой.

Правило простое: тесты не пишут в файлы проекта. Здесь это гарантируется
автоматически и для всех тестов сразу, а не «если кто-то вспомнит».
"""
from __future__ import annotations

import pytest

from env import site_outcomes


@pytest.fixture(autouse=True)
def _isolate_work_files(tmp_path, monkeypatch):
    """Увести корпус сверок и реестр клинчей в tmp на время каждого теста."""
    monkeypatch.setattr(site_outcomes, "OUTCOMES_FILE", tmp_path / "site_outcomes.jsonl")
    monkeypatch.delenv("DOF_SITE_OUTCOMES", raising=False)
    monkeypatch.delenv("DOF_RUN_TAG", raising=False)
    monkeypatch.delenv("DOF_DUMP_MAP", raising=False)
    monkeypatch.delenv("DOF_WEDGED_FILE", raising=False)
    yield
