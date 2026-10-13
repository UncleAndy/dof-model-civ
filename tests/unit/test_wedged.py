"""Реестр клинчей и выключатель любопытства.

Клинч — это **измеренный** факт (действие×местность), а не догадка: его нельзя
вывести из правил, можно только исполнить и увидеть, что управление не
вернулось. Значит, у него должны быть те же свойства, что и у прочих измерений:
он переживает матч, он отменяет надбавку за «эксперимент» и он исключает
действие из кандидатов.

ПРАВИЛО ОТСЕЧЕНИЯ проверено замером: одиночная запись — подозрение, клин — по
повтору или по прямому отказу стенда. Так вышло потому, что одиночная запись
секла ИСПРАВНОЕ действие: реестр записал `unit/build_city` (основание города
работает всегда), и из-за этого основание молча выпало из оценки действий.
Здесь это и закреплено: одиночного наблюдения для вычёркивания мало.
"""
from __future__ import annotations

import json

import pytest

from env import config as cfg
from env import wedged
from env.action_family import family_of
from env.experiments import (
    action_known,
    probe_bonus,
    uncertainty_bonus,
)


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Отдельный файл реестра на каждый тест — тесты не видят прогоны."""
    path = tmp_path / "wedged.json"
    monkeypatch.setattr(wedged, "WEDGED_FILE", path)
    wedged.reset_cache()
    yield path
    wedged.reset_cache()


class TestWedgedRegistry:
    def test_records_and_persists_the_wedge(self, registry):
        assert wedged.record_wedged("unit", "irrigate_5_3", turn=4,
                                    context={"agent": "dof_economic"}) is True
        wedged.reset_cache()  # другой процесс: читаем с диска, а не из кэша
        # Одно наблюдение — подозрение, а не клин: вычёркивать ещё нельзя.
        assert wedged.is_wedged("unit", "irrigate_5_3") is False
        wedged.record_wedged("unit", "irrigate_9_9", turn=9)
        wedged.reset_cache()
        assert wedged.is_wedged("unit", "irrigate_5_3") is True
        data = json.loads(registry.read_text())
        key = "unit/irrigate"
        assert key in data
        assert data[key]["first_turn"] == 4
        assert data[key]["context"]["agent"] == "dof_economic"

    def test_unscoped_observations_keep_family_fallback(self, registry):
        # Старые записи без координат остаются семейными для вызовов,
        # которым контекст недоступен. Forecast-вызовы передают позицию.
        wedged.record_wedged("unit", "irrigate_5_3")
        wedged.record_wedged("unit", "irrigate_40_-2")
        assert wedged.is_wedged("unit", "irrigate_9_9") is True
        assert family_of("irrigate_9_9") == "irrigate"

    def test_context_aware_wedge_does_not_leak_between_locations(self, registry):
        site_a = {"position": (5, 3)}
        site_b = {"position": (9, 9)}
        wedged.record_wedged("unit", "build_city", context=site_a)
        wedged.record_wedged("unit", "build_city", context=site_a)
        assert wedged.is_wedged("unit", "build_city", context=site_a) is True
        assert wedged.is_wedged("unit", "build_city", context=site_b) is False

    def test_success_resolves_unscoped_history_without_erasing_it(self, registry):
        wedged.record_wedged("unit", "build_city")
        wedged.record_wedged("unit", "build_city")
        site_a = {"position": (5, 3)}
        site_b = {"position": (9, 9)}
        assert wedged.is_wedged("unit", "build_city", context=site_a) is True

        wedged.record_success("unit", "build_city", context=site_a)
        assert wedged.is_wedged("unit", "build_city", context=site_a) is False
        assert wedged.is_wedged("unit", "build_city", context=site_b) is True
        assert wedged.is_wedged("unit", "build_city") is True
        entry = json.loads(registry.read_text())["unit/build_city"]
        assert entry["seen"] == 2
        success = entry["successes_by_context"]["position:5,3"]
        assert success["resolved_unscoped_seen"] == 2

    def test_success_at_one_position_keeps_another_position_wedged(self, registry):
        site_a = {"position": (5, 3)}
        site_b = {"position": (9, 9)}
        for _ in range(2):
            wedged.record_wedged("unit", "build_city", context=site_a)
            wedged.record_wedged("unit", "build_city", context=site_b)
        wedged.record_success("unit", "build_city", context=site_a)
        assert wedged.is_wedged("unit", "build_city", context=site_a) is False
        assert wedged.is_wedged("unit", "build_city", context=site_b) is True

    def test_success_resets_threshold_before_same_site_can_rewedge(self, registry):
        site = {"position": (5, 3)}
        wedged.record_wedged("unit", "build_city", context=site)
        wedged.record_wedged("unit", "build_city", context=site)
        assert wedged.is_wedged("unit", "build_city", context=site) is True

        wedged.record_success("unit", "build_city", context=site)
        assert wedged.is_wedged("unit", "build_city", context=site) is False
        entry = json.loads(registry.read_text())["unit/build_city"]
        assert entry["seen"] == 2
        assert entry["scopes"]["position:5,3"]["resolved_seen"] == 2
        assert entry["scopes"]["position:5,3"]["successes"] == 1

        wedged.record_wedged("unit", "build_city", context=site)
        assert wedged.is_wedged("unit", "build_city", context=site) is False
        wedged.record_wedged("unit", "build_city", context=site)
        assert wedged.is_wedged("unit", "build_city", context=site) is True

    def test_the_record_is_per_controller(self, registry):
        wedged.record_wedged("unit", "irrigate_5_3")
        wedged.record_wedged("unit", "irrigate_9_9")
        assert wedged.is_wedged("city", "irrigate_5_3") is False

    def test_recording_twice_is_not_a_new_measurement(self, registry):
        assert wedged.record_wedged("unit", "irrigate_5_3") is True
        # Второе наблюдение — не новая запись о новом клине, а подтверждение
        # прежнего: записей по-прежнему одна, но «видели» уже дважды.
        assert wedged.record_wedged("unit", "irrigate_9_9") is False
        assert len(json.loads(registry.read_text())) == 1
        assert json.loads(registry.read_text())["unit/irrigate"]["seen"] == 2

    def test_an_empty_name_is_never_wedged(self, registry):
        assert wedged.record_wedged("", "") is False
        assert wedged.is_wedged("", "") is False

    def test_a_missing_file_means_no_knowledge_yet(self, registry):
        assert registry.exists() is False
        assert wedged.is_wedged("unit", "irrigate_5_3") is False


class TestWedgedIsKnowledge:
    def test_a_wedged_action_counts_as_known(self, registry):
        wedged.record_wedged("unit", "irrigate_5_3")
        wedged.record_wedged("unit", "irrigate_9_9")
        assert action_known("unit", "irrigate_5_3") is True
        # и надбавки за «эксперимент» оно не получает — мы уже знаем ответ
        assert uncertainty_bonus("unit", "irrigate_5_3",
                                 {"AXIOM4_PENALTY_OPTIONS": 0.5}, 0) == 0.0

    def test_a_wedged_action_is_cut_from_the_candidates(self, registry):
        from env.action_mapper import CivAction, estimate_dof_delta
        from env.entity_extractor import EntityState, SystemStateMatrix

        state = SystemStateMatrix(
            entities={"unit_3": EntityState(entity_id="unit_3", entity_type="unit",
                                            dof_count=2.0, current_dof=0.2)},
        )
        action = CivAction(ctrl_type="unit", actor_id=3, action_name="irrigate_5_3")
        wedged.record_wedged("unit", "irrigate_5_3")
        wedged.record_wedged("unit", "irrigate_9_9")
        # Пустая дельта — действие вырезано из шортлиста, а не оценено нулём:
        # ноль выглядел бы как «эффекта нет» и агент выбрал бы его снова.
        assert estimate_dof_delta(action, state) == {}

    def test_scoped_wedge_uses_the_actor_position(self, registry):
        from env.action_mapper import CivAction, estimate_dof_delta
        from env.entity_extractor import BridgeCalibration, EntityState, SystemStateMatrix

        wedged.record_wedged("unit", "build_city", context={"position": (5, 3)})
        wedged.record_wedged("unit", "build_city", context={"position": (5, 3)})
        action = CivAction(ctrl_type="unit", actor_id=3, action_name="build_city")
        state = SystemStateMatrix(
            entities={"unit_3": EntityState(entity_id="unit_3", entity_type="unit",
                                            dof_count=2.0, current_dof=0.2)},
            positions={"unit_3": (9, 9)},
            bridge=BridgeCalibration(new_city_options=5.0),
        )
        assert estimate_dof_delta(action, state) == {"unit_3": 3.0}

        state.positions["unit_3"] = (5, 3)
        assert estimate_dof_delta(action, state) == {}


class TestCuriositySwitch:
    def test_off_means_no_bonus_at_all(self, monkeypatch):
        monkeypatch.setattr(cfg, "CURIOSITY_ENABLED", False)
        vals = {"AXIOM4_PENALTY_OPTIONS": 0.5}
        assert uncertainty_bonus("city", "buy_improvement", vals, 0) == 0.0
        assert probe_bonus("unit", "build_city",
                           [{"key": "new_city_options"}], lambda key: 0, vals) == 0.0

    def test_on_means_the_bonus_returns(self, monkeypatch):
        monkeypatch.setattr(cfg, "CURIOSITY_ENABLED", True)
        vals = {"AXIOM4_PENALTY_OPTIONS": 0.5}
        assert uncertainty_bonus("city", "buy_improvement", vals, 0) == pytest.approx(0.5)
        assert probe_bonus("unit", "build_city",
                           [{"key": "new_city_options"}], lambda key: 0,
                           vals) == pytest.approx(0.5)
