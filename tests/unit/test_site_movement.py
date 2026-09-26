"""Движение к лучшей площадке: у поселенца должен быть повод идти.

Поселенец на бесплодной земле не может основать город — площадка вырезается
гейтом. Единственный способ реализовать движок роста — дойти туда, где город
сможет расти. Здесь проверяется, что выигрыш от перехода считается по той же
формуле города, дисконтируется как будущая возможность и попадает в бридж на
действия перемещения, а не на что попало.
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


def make_map(size: int = 14, fill=(0, 0, 0), tiles=None) -> dict:
    out = np.zeros((size, size, 6), dtype=float)
    out[:, :, 0], out[:, :, 1], out[:, :, 2] = fill
    for (x, y), v in (tiles or {}).items():
        out[x, y, 0], out[x, y, 1], out[x, y, 2] = v
    return {"output": out}


def barren_here_rich_there() -> dict:
    """Носитель на бесплодной земле; земля, которая кормит, — ВНЕ области города.

    Ключевая деталь: область влияния города — 21 клетка (радиус 2), поэтому
    богатая земля должна лежать дальше двух клеток, иначе её можно обрабатывать
    прямо отсюда и уходить незачем.
    """
    tiles = {}
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            tiles[(5 + dx, 5 + dy)] = (1, 0, 0)          # вокруг бесплодно
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            # Область города шире шага: чтобы земля была недостижима и с одного
            # шага (юнит на (5,5) + шаг = область до x=8), кладём её на x=9..11.
            tiles[(10 + dx, 5 + dy)] = (3, 2, 1)
    return make_map(tiles=tiles)


def carrier_obs(x: int = 5, y: int = 5, move_rate: int = 2) -> dict:
    return {
        "unit": {
            "7": {"rule_name": "Settlers", "x": x, "y": y, "type_move_rate": move_rate,
                  "type_hp": 20, "health": 20},
        },
        "map": barren_here_rich_there(),
    }


class TestMoveGain:
    def test_barren_start_creates_a_reason_to_walk(self):
        ex = GameStateExtractor(my_player_id=0)
        result = ex.extract(carrier_obs(), {}, 1)
        bridge = result.state.bridge

        assert "unit_7" in bridge.nonviable_carrier_sites      # здесь город запрещён
        assert "unit_7" in bridge.site_move_gain_by_unit       # но есть куда идти
        gain = bridge.site_move_gain_by_unit["unit_7"]
        report = bridge.site_move_report["unit_7"]
        assert gain > 0
        assert report["current_value"] == 0.0                   # на бесплодной — 0
        assert report["best_value"] > 0
        # Выигрыш дисконтируется как будущая возможность, а не берётся целиком.
        assert gain == pytest.approx(cfg.W_FUTURE_UNIT * report["raw_gain"], rel=1e-6)
        # Цель — в пределах хода носителя и именно богатая сторона.
        target = report["target"]
        assert max(abs(target["dx"]), abs(target["dy"])) <= report["reach"]
        # Город, основанный в цели, обязан обрести еду: здесь площадь накрывает
        # богатую землю, а исходная — нет.
        assert target["food"] >= 6.0
        assert target["target_x"] >= 7

    def test_reach_is_limited_by_the_units_move_rate(self):
        ex = GameStateExtractor(my_player_id=0)
        slow = ex.extract(carrier_obs(move_rate=1), {}, 1)
        fast = ex.extract(carrier_obs(move_rate=2), {}, 1)
        # На расстоянии 2 клетки медленный юнит не видит богатой площадки.
        assert "unit_7" not in slow.state.bridge.site_move_gain_by_unit
        assert "unit_7" in fast.state.bridge.site_move_gain_by_unit

    def test_standing_on_the_best_site_gives_no_reason_to_leave(self):
        # Однородно богатая земля: любая площадка равна любой другой, значит
        # переход не даёт ничего и оплачивать его нечем.
        obs = carrier_obs(x=7, y=5, move_rate=2)
        obs["map"] = make_map(size=14, fill=(3, 2, 1))
        ex = GameStateExtractor(my_player_id=0)
        result = ex.extract(obs, {}, 1)
        bridge = result.state.bridge
        assert "unit_7" in bridge.new_city_options_by_unit       # здесь селиться можно
        assert "unit_7" not in bridge.site_move_gain_by_unit     # и идти незачем

    def test_no_invented_gain_without_a_map(self):
        obs = carrier_obs()
        obs.pop("map")
        ex = GameStateExtractor(my_player_id=0)
        bridge = ex.extract(obs, {}, 1).state.bridge
        assert bridge.site_move_gain_by_unit == {}


class TestMovementActionIsPriced:
    def _state(self, *, gain: float | None) -> SystemStateMatrix:
        bridge = BridgeCalibration(new_city_options=3.0)
        if gain is not None:
            bridge.site_move_gain_by_unit["unit_7"] = gain
        return SystemStateMatrix(
            entities={"unit_7": EntityState(entity_id="unit_7", entity_type="unit",
                                            dof_count=4.0, current_dof=0.4)},
            bridge=bridge,
        )

    def test_goto_carries_the_site_gain(self):
        action = CivAction(ctrl_type="unit", actor_id=7, action_name="goto_120")
        assert estimate_dof_delta(action, self._state(gain=1.4)) == {"unit_7": 1.4}

    def test_other_unit_actions_are_not_paid_the_walk(self):
        action = CivAction(ctrl_type="unit", actor_id=7, action_name="fortify")
        assert estimate_dof_delta(action, self._state(gain=1.4)).get("unit_7", 0.0) == 0.0

    def test_no_gain_no_delta(self):
        action = CivAction(ctrl_type="unit", actor_id=7, action_name="goto_120")
        assert estimate_dof_delta(action, self._state(gain=None)).get("unit_7", 0.0) == 0.0
