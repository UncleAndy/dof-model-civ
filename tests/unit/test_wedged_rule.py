"""Правило реестра клинов: один случай — подозрение, клин — по повтору или отказу.

Измерено, почему это правило нужно: реестр записал `unit/build_city` по ОДНОМУ
случаю, а основание города у нас работает постоянно — то есть одиночная запись
сечёт исправное действие. Цена ошибок несимметрична:

* одиночный ложный клин стоит нам матча (действие исключено из выбора);
* ложное исключение стоит возможности, причём молча — основание города
  выпадало из оценки действий (`estimate_dof_delta` возвращает пусто) и агент
  переставал его рассматривать.

Поэтому режем только то, что подтверждено: повторный клин (два наблюдения) или
прямой отказ стенда (`Action ... is not valid`), который является утверждением о
невозможности, а не о неудаче.
"""
from __future__ import annotations

import json

import pytest

from env import wedged


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    path = tmp_path / "wedged.json"
    monkeypatch.setattr(wedged, "WEDGED_FILE", path)
    wedged.reset_cache()
    yield path
    wedged.reset_cache()


def _sightings(path, key):
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return int(data.get(key, {}).get("seen", 0))


def test_one_timeout_sighting_is_a_suspicion_not_a_wedge(registry):
    wedged.record_wedged("unit", "build_city", turn=1, context={"agent": "t"})
    assert _sightings(registry, "unit/build_city") == 1
    assert not wedged.is_wedged("unit", "build_city"), (
        "одиночная запись не должна вычёркивать действие: измерено на unit/build_city, "
        "которое на самом деле работает"
    )


def test_a_repeat_makes_it_a_wedge(registry):
    wedged.record_wedged("city", "produce_Library", turn=1)
    wedged.record_wedged("city", "produce_Library", turn=7)
    assert _sightings(registry, "city/produce_Library") == 2
    assert wedged.is_wedged("city", "produce_Library")


def test_a_direct_refusal_is_a_wedge_at_once(registry):
    wedged.record_wedged("city", "produce_Marketplace", turn=12, reason="refused")
    assert _sightings(registry, "city/produce_Marketplace") == 1
    assert wedged.is_wedged("city", "produce_Marketplace"), (
        "отказ стенда (`Action produce_X of N is not valid`) — утверждение о "
        "невозможности, его хватает одного"
    )


def test_unknown_action_is_not_wedged(registry):
    assert not wedged.is_wedged("unit", "goto")
    assert not wedged.is_wedged("", "goto")