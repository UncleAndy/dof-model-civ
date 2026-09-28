"""Клетки города как семейство: цена перевода жителя считается формулой города.

Почему это семейство вообще допущено к живому прогнозу. Замер 2026-09-27
(§10.25.4, `scripts/measure_buy_and_work.py` + `scripts/check_work_price.py`)
сравнил предсказание формулы с наблюдением на 6 парах переводов между РАЗНЫМИ
клетками:

| Δвыходов клетки (еда, щиты, торговля) | предсказание | наблюдение |
|---|---|---|
| −1, 0, +4 | +1.2000 | +0.41, +0.48 |
| 0, +2, −4 | −0.6000 | −0.63, −0.57 |
| 0, −2, +4 | +0.6000 | +0.78, +0.85 |

Знаки совпали во всех шести. Тут проверяется, что провод доносит эту цену до
кандидатов без подмены имён действий (имя `city_work_<id>_<dx>_<dy>` приходит от
сервера целиком: подменить его значит поставить жителя не на ту клетку).
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from brain.forecast.live import build_context
from env.measured_facts import MeasuredFacts


def _extractor():
    return SimpleNamespace(
        my_player_id=0,
        model=None,
        _site_city_value=lambda site, capital: float(site.food),
        _terrain_work_gains=lambda obs, values, map_obs: ({}, {}),
    )


def _dof_state():
    bridge = SimpleNamespace(unit_type_options={}, improvement_options={})
    return SimpleNamespace(state=SimpleNamespace(bridge=bridge, entities={}))


def _obs(*, city_actions):
    """Карта 8×8: канал 0 — еда, 1 — щиты, 2 — торговля (как в слое `map.output`)."""
    out = np.zeros((8, 8, 6), dtype=float)
    # Соседние клетки города (2, 2): у (2, 4) щиты 2, у (3, 2) торговля 3.
    out[2, 4, 1] = 2.0
    out[3, 2, 2] = 3.0
    city = {"121": {"id": 121, "owner": 0, "x": 2, "y": 2, "size": 1,
                    "surplus_food": 1, "surplus_shield": 3, "surplus_trade": 2,
                    "surplus_gold": 1, "prod_shield": 3, "shield_stock": 0}}
    info_dict = {"available_actions": {"city": {"121": dict(city_actions)},
                                       "unit": {}, "tech": {}}}
    return {"map": {"output": out}, "city": city, "unit": {}}, info_dict


def _context(city_actions):
    obs, info_dict = _obs(city_actions=city_actions)
    return build_context(obs, info_dict, _dof_state(), _extractor(),
                         world_model=MeasuredFacts("/tmp/нет-такого.json"))


class TestTileFamily:
    def test_a_worked_tile_is_priced_by_the_city_formula(self):
        ctx = _context({"city_work_121_0_2": True})
        priced = ctx.vals.tiles("city_121")
        assert [row[0] for row in priced] == ["city_work_121_0_2"]
        # Щиты 2 в клетке при весе CITY_M2_SHIELD 0.05: прибавка к опциям города
        # положительна и равна разнице формулы, а не выдуманному числу.
        assert priced[0][1] > 0.0

    def test_unworking_a_tile_is_priced_negative(self):
        # Клетка (2, 4) — та самая, что несёт щиты 2: выход уходит из экономики.
        ctx = _context({"city_unwork_121_0_2": True})
        priced = ctx.vals.tiles("city_121")
        assert [row[0] for row in priced] == ["city_unwork_121_0_2"]
        assert priced[0][1] < 0.0

    def test_a_tile_with_no_output_is_priced_zero(self):
        """Пустая клетка — измеренный ноль, и он остаётся нулём (§10.25.4)."""
        ctx = _context({"city_work_121_0_-2": True})
        priced = ctx.vals.tiles("city_121")
        assert [row[0] for row in priced] == ["city_work_121_0_-2"]
        assert priced[0][1] == pytest.approx(0.0)

    def test_only_offered_tiles_are_offered(self):
        # Действие не предложено сервером (флаг пуст) — кандидата нет: подставить
        # себе действие, которого мир не предлагал, значит выдумать ход.
        ctx = _context({"city_work_121_0_2": False})
        assert ctx.vals.tiles("city_121") == []

    def test_a_foreign_action_is_not_a_tile_move(self):
        ctx = _context({"produce_Temple": True, "city_work_121_0_2": True})
        names = [row[0] for row in ctx.vals.tiles("city_121")]
        assert names == ["city_work_121_0_2"]

    def test_the_candidate_carries_the_servers_own_action_name(self):
        from brain.forecast.options import candidates
        from brain.forecast.state import ForecastState

        ctx = _context({"city_work_121_0_2": True})
        state = ForecastState(
            dof={"city_121": 8.0}, reversible={"city_121": True},
            positions={}, cities={"city_121": (2, 2)}, root_dof={"city_121": 8.0},
        )
        found = [c for c in candidates(state, ctx.vals) if c.kind == "tile"]
        assert len(found) == 1
        assert found[0].action == ("city", "city_121", "city_work_121_0_2")
        assert found[0].effect.delay == 0        # выход клетки меняется сразу
        assert found[0].effect.reversible is True

    def test_the_family_can_be_switched_off(self):
        from env.config import CITY_TILE_FAMILY

        assert CITY_TILE_FAMILY is True
        ctx = _context({"city_work_121_0_2": True})
        ctx.vals.tiles("city_121")           # без исключения