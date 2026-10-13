"""Семейный запрет — только для действия, которое НИ РАЗУ не удалось (§13.274).

Измерено на живом реестре:

* `unit/plant` — 26 отказов в 25 разных клетках, успехов НОЛЬ → резать;
* `unit/build_city` — 3 отказа и 37 успехов → играть (иначе гибнет основание города);
* `city/city_work` — 53 отказа без координат, успехов ноль → резать.

Почему отдельная функция, а не правка `is_wedged`: его семантика закреплена тестом
`test_success_resolves_unscoped_history_without_erasing_it` («успех в одной позиции не
разрешает другие позиции»). Это нарочное решение, и мы его не трогаем — добавляем
рядом ровно то, чего не хватает пути юнитов.
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


def test_unknown_action_is_not_blocked(registry):
    assert wedged.is_wedged_family("unit", "plant") is False


def test_a_single_failure_is_only_a_suspicion(registry):
    wedged.record_wedged("unit", "plant", turn=1, context={"position": [1, 1]})
    assert wedged.is_wedged_family("unit", "plant") is False


def test_many_failures_across_distinct_tiles_with_no_success_are_blocked(registry):
    """`unit/plant` живьём: 26 отказов в 25 разных клетках, ни одного успеха."""
    for site in range(1, 6):
        wedged.record_wedged("unit", "plant", turn=site,
                            context={"position": [site, site]})
    assert wedged.is_wedged_family("unit", "plant") is True


def test_a_working_action_is_never_blocked_by_old_failures(registry):
    """`unit/build_city` живьём: 3 отказа и 37 успехов — основание города гибнуть не должно."""
    for _ in range(3):
        wedged.record_wedged("unit", "build_city", turn=1,
                            context={"position": [1, 1]})
    assert wedged.is_wedged_family("unit", "build_city") is True, "пока успехов нет — режем"

    wedged.record_success("unit", "build_city", turn=2, context={"position": [2, 2]})
    assert wedged.is_wedged_family("unit", "build_city") is False, (
        "успех доказывает, что действие работает: семейный запрет обязан сняться")


def test_blocking_does_not_depend_on_the_wedged_position(registry):
    """У действия без единого успеха режется СЕМЬЯ, а не только падавшие клетки.

    Иначе следующая клетка снова получит это действие и снова убьёт матч — измерено:
    экономическая рука залипала на втором ходу в каждой партии, отдельная клетка падала
    лишь однажды, и позиционное правило её не подтверждало.
    """
    for site in (3, 7):
        wedged.record_wedged("unit", "plant", turn=1, context={"position": [site, site]})
    assert wedged.is_wedged_family("unit", "plant") is True
    assert wedged.is_wedged("unit", "plant", context={"position": [9, 9]}) is False, (
        "позиционное правило остаётся как было — оно подтверждает только падавшую клетку")
