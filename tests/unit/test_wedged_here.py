"""Позиционный запрет — ТОЛЬКО по самой клетке, без устаревших семейных отказов (§13.275).

Измерено на живом прогоне: `is_wedged(..., context=позиция)` включает и семейный остаток,
поэтому `unit/build_city` (3 отказа и 37 успехов) резался в НОВЫХ клетках **176 раз за
прогон** — и основание города гибло: обе руки отыграли 20 ходов и получили счёт 0.0.

Нужен вопрос «падало ли ИМЕННО ЗДЕСЬ»: он и есть вторая половина правила §13.274 —
исправное действие режем только в тех клетках, где оно уже падало.
"""
from __future__ import annotations

import pytest

from env import wedged


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    path = tmp_path / "wedged.json"
    monkeypatch.setattr(wedged, "WEDGED_FILE", path)
    wedged.reset_cache()
    yield path
    wedged.reset_cache()


def test_an_unknown_position_is_not_blocked(registry):
    wedged.record_wedged("unit", "build_city", turn=1, context={"position": [1, 1]})
    wedged.record_wedged("unit", "build_city", turn=1, context={"position": [1, 1]})
    assert wedged.is_wedged_here("unit", "build_city", (9, 9)) is False


def test_a_position_that_failed_twice_is_blocked(registry):
    for _ in range(2):
        wedged.record_wedged("unit", "build_city", turn=1, context={"position": [1, 1]})
    assert wedged.is_wedged_here("unit", "build_city", (1, 1)) is True


def test_a_success_at_the_position_clears_it(registry):
    for _ in range(2):
        wedged.record_wedged("unit", "build_city", turn=1, context={"position": [1, 1]})
    wedged.record_success("unit", "build_city", turn=2, context={"position": [1, 1]})
    assert wedged.is_wedged_here("unit", "build_city", (1, 1)) is False


def test_stale_family_failures_do_not_leak_into_a_new_position(registry):
    """Тот самый измеренный случай: три устаревших семейных отказа не должны резать новую клетку."""
    for _ in range(3):
        wedged.record_wedged("unit", "build_city", turn=1)      # без координат
    wedged.record_success("unit", "build_city", turn=2, context={"position": [2, 2]})
    assert wedged.is_wedged_here("unit", "build_city", (5, 5)) is False, (
        "иначе основание города гибнет: измерено 176 исключений за прогон, счёт 0.0")


def test_no_position_means_no_local_block(registry):
    for _ in range(3):
        wedged.record_wedged("unit", "build_city", turn=1, context={"position": [1, 1]})
    assert wedged.is_wedged_here("unit", "build_city", None) is False
