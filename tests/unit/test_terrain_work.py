"""Цена работ на террейне: рабочий поднимает DoF города (пункт 1).

Проверяем, что цена берётся ИЗ ИЗМЕРЕНИЙ и адресуется городу, который
обрабатывает клетку: измеренная экстра даёт выгоду, неизмеренная — ноль,
уже стоящая экстра — ноль, клетка вне города — ноль.
"""
from __future__ import annotations

import numpy as np
import pytest

from env import config as cfg
from env.action_mapper import CivAction, estimate_dof_delta
from env.entity_extractor import (
    BridgeCalibration,
    EntityState,
    GameStateExtractor,
    SystemStateMatrix,
)
from env.terrain_work import (
    MEASURED_WORK_TURNS,
    is_terrain_transform,
    tile_effect,
    work_extra,
)

TERRAIN = ["Inaccessible", "Lake", "Ocean", "Deep Ocean", "Glacier", "Desert",
           "Forest", "Grassland", "Hills", "Jungle", "Mountains", "Plains",
           "Swamp", "Tundra"]
EXTRAS = ["Irrigation", "Mine", "Oil Well", "Pollution", "Minor Tribe Village",
          "Farmland", "Fallout", "Fortress", "Airbase", "Buoy", "Ruins", "Road",
          "Railroad", "River", "Gold", "Iron", "Game", "Furs", "Coal", "Fish",
          "Fruit", "Gems", "Buffalo", "Wheat", "Oasis", "Peat", "Pheasant",
          "Resources", "Ivory", "Silk", "Spice", "Whales", "Wine", "Oil"]


def make_obs(*, tiles=None, extras=None, cities=None, units=None, size=12) -> dict:
    """Синтетическое наблюдение с картой, городами и юнитами."""
    terrain = np.zeros((size, size), dtype=int)
    output = np.zeros((size, size, 6), dtype=float)
    extras_arr = np.zeros((size, size, len(EXTRAS)), dtype=bool)
    for (x, y), spec in (tiles or {}).items():
        tid, out = spec[0], spec[1]
        terrain[x, y] = TERRAIN.index(tid)
        output[x, y, 0], output[x, y, 1], output[x, y, 2] = out
    for (x, y), extra in (extras or {}).items():
        extras_arr[x, y, EXTRAS.index(extra)] = True
    return {
        "map": {"terrain": terrain, "output": output, "extras": extras_arr},
        "city": cities or {},
        "unit": units or {},
    }


def a_city(cid="121", x=6, y=6, **over) -> dict:
    city = {"id": cid, "owner": 0, "x": x, "y": y, "size": 1,
            "surplus_food": 2, "surplus_shield": 1, "surplus_trade": 2,
            "food_stock": 0, "granary_size": 20, "improvements": [],
            "city_corruption": 0}
    city.update(over)
    return {cid: city}


def a_worker(uid="8", x=6, y=7) -> dict:
    return {uid: {"rule_name": "Workers", "type_worker": True, "x": x, "y": y,
                  "type_hp": 10, "health": 10, "type_move_rate": 1}}


class TestWorkVocabulary:
    def test_actions_map_to_the_extra_they_place(self):
        assert work_extra("irrigation") == "Irrigation"
        assert work_extra("build_road") == "Road"
        assert work_extra("mine") == "Mine"
        assert work_extra("railroad_3") == "Railroad"
        assert work_extra("cultivate") is None       # это не экстра, а смена террейна
        assert work_extra("fortify") is None

    def test_transform_actions_are_recognised_separately(self):
        assert is_terrain_transform("cultivate")
        assert is_terrain_transform("transform_terrain")
        assert not is_terrain_transform("build_road")

    def test_measured_work_takes_four_turns_by_observation(self):
        assert MEASURED_WORK_TURNS == 4


class TestEffectTable:
    VALS = {"MEASURED_EXTRA_EFFECTS": dict(cfg.MEASURED_EXTRA_EFFECTS)}

    def test_measured_extra_reports_its_effect(self):
        # Coal измерен на живом стенде: Hills+Coal (1,2,0) против Hills (1,0,0).
        assert tile_effect("Coal", "Hills", (), self.VALS) == (0.0, 2.0, 0.0)

    def test_unmeasured_extra_returns_none_not_zero(self):
        # Mine пока не измерена: это НЕ «эффекта нет», а «не знаем». Разница
        # важна: неизмеренное обязано молчать, а не притворяться нулём.
        assert tile_effect("Mine", "Hills", (), self.VALS) is None

    def test_measured_work_on_a_given_terrain_is_recorded(self):
        # Замерено на живом стенде: ирригация на равнине ставит экстру за 3 хода,
        # но выхода не добавляет (смысл — открыть ферму, а не еду).
        assert tile_effect("Irrigation", "Grassland", (), self.VALS) == (0.0, 0.0, 0.0)
        # А на пустыне это НЕ измерено — и потому не обобщается.
        assert tile_effect("Irrigation", "Desert", (), self.VALS) is None

    def test_measured_roads_place_the_extra_without_output(self):
        # Замерено на трёх террейнах: дорога ставит экстру Road, выхода не даёт
        # (в этой версии стенда дорога — только перемещение).
        for terrain in ("Grassland", "Plains", "Hills"):
            assert tile_effect("Road", terrain, (), self.VALS) == (0.0, 0.0, 0.0)
        assert tile_effect("Road", "Forest", (), self.VALS) is None

    def test_extra_already_present_is_worthless(self):
        assert tile_effect("Coal", "Hills", ("Coal",), self.VALS) == (0.0, 0.0, 0.0)

    def test_non_effect_extras_are_recorded_as_zero(self):
        assert tile_effect("River", "Forest", (), self.VALS) == (0.0, 0.0, 0.0)


class TestWorkGainReachesTheCity:
    def _bridge(self, *, obs) -> BridgeCalibration:
        return GameStateExtractor(my_player_id=0).extract(obs, {}, 1).state.bridge

    def test_measured_work_on_a_tile_the_city_works_pays_the_city(self):
        # Холм с Coal через клетку от города: шахта там бессмысленна (Coal уже
        # измерен и стоит), поэтому берём город рядом с холмом БЕЗ экстры и
        # временно подсовываем измеренный эффект для Mine.
        obs = make_obs(tiles={(6, 6): ("Grassland", (2, 0, 0)),
                              (6, 7): ("Hills", (1, 0, 0))},
                       cities=a_city(x=6, y=6), units=a_worker(x=6, y=7))
        extractor = GameStateExtractor(my_player_id=0)
        extractor.model.observe("MEASURED_EXTRA_EFFECTS",
                                {"Mine": (0.0, 1.0, 0.0)}, 1)
        bridge = extractor.extract(obs, {}, 1).state.bridge
        gains = bridge.terrain_work_gain_by_unit.get("unit_8", {})
        assert gains.get("Mine", 0.0) > 0
        report = bridge.terrain_work_report["unit_8"]["Mine"]
        assert report["city"] == "city_121"
        assert report["effect"] == [0.0, 1.0, 0.0]

    def test_unmeasured_work_pays_nothing(self):
        obs = make_obs(tiles={(6, 6): ("Grassland", (2, 0, 0)),
                              (6, 7): ("Grassland", (2, 0, 0))},
                       cities=a_city(x=6, y=6), units=a_worker(x=6, y=7))
        bridge = self._bridge(obs=obs)
        assert bridge.terrain_work_gain_by_unit == {}

    def test_no_city_in_range_pays_nothing(self):
        obs = make_obs(tiles={(6, 6): ("Grassland", (2, 0, 0)),
                              (20, 20): ("Hills", (1, 0, 0))},
                       cities=a_city(x=2, y=2), units=a_worker(x=20, y=20),
                       size=24)
        extractor = GameStateExtractor(my_player_id=0)
        extractor.model.observe("MEASURED_EXTRA_EFFECTS",
                                {"Mine": (0.0, 1.0, 0.0)}, 1)
        bridge = extractor.extract(obs, {}, 1).state.bridge
        assert bridge.terrain_work_gain_by_unit == {}

    def test_non_worker_units_are_not_paid_for_work(self):
        units = {"9": {"rule_name": "Explorer", "type_worker": False, "x": 6, "y": 7,
                       "type_hp": 10, "health": 10, "type_move_rate": 3}}
        obs = make_obs(tiles={(6, 6): ("Grassland", (2, 0, 0)),
                              (6, 7): ("Hills", (1, 0, 0))},
                       cities=a_city(x=6, y=6), units=units)
        extractor = GameStateExtractor(my_player_id=0)
        extractor.model.observe("MEASURED_EXTRA_EFFECTS",
                                {"Mine": (0.0, 1.0, 0.0)}, 1)
        bridge = extractor.extract(obs, {}, 1).state.bridge
        assert "unit_9" not in bridge.terrain_work_gain_by_unit


class TestWorkActionIsPriced:
    def _state(self, gains) -> SystemStateMatrix:
        bridge = BridgeCalibration(new_city_options=3.0)
        if gains:
            bridge.terrain_work_gain_by_unit["unit_8"] = gains
        return SystemStateMatrix(
            entities={"unit_8": EntityState(entity_id="unit_8", entity_type="unit",
                                            dof_count=1.0, current_dof=0.1)},
            bridge=bridge,
        )

    def test_irrigation_carries_the_measured_gain(self):
        action = CivAction(ctrl_type="unit", actor_id=8, action_name="irrigation")
        delta = estimate_dof_delta(action, self._state({"Irrigation": 0.42}))
        assert delta == {"unit_8": 0.42}

    def test_a_work_action_without_a_measured_effect_is_not_paid(self):
        action = CivAction(ctrl_type="unit", actor_id=8, action_name="irrigation")
        assert estimate_dof_delta(action, self._state({"Mine": 0.42})) \
            .get("unit_8", 0.0) == 0.0

    def test_transform_actions_are_not_priced_as_extras(self):
        action = CivAction(ctrl_type="unit", actor_id=8, action_name="cultivate")
        assert estimate_dof_delta(action, self._state({"Irrigation": 0.42})) \
            .get("unit_8", 0.0) == 0.0
