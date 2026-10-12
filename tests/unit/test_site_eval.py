"""Тесты оценки площадки и контрфактического роста (фактор (б)).

Проверяем ровно те свойства, которые подтверждены на живом стенде:
  * область влияния — 21 клетка (квадрат 5×5 без угловых);
  * работает `size + 1` клеток, центральная — бесплатно;
  * нераскрытые клетки не считаются нулём (Axiom 5/7);
  * гейт `SITE_MIN_FOOD` вырезает «города-однодневки», а не штрафует их;
  * сток задержки = прирост DoF контрфактического города за ход, с полом 0.02;
  * на реальном наблюдении сток РАСТЁТ с возрастом носителя (то есть цена
    задержки видна, чего не было при плоском прокси).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from env import config as cfg
from env.action_mapper import CivAction, estimate_dof_delta
from env.entity_extractor import (
    BridgeCalibration,
    EntityState,
    GameStateExtractor,
    SystemStateMatrix,
    city_options,
    is_population_carrier,
)
from env.site_eval import (
    CITY_RADIUS_SQ,
    WORKABLE_OFFSETS,
    citizens_per_turn,
    counterfactual_growth_sink_per_turn,
    evaluate_site,
    growth_box,
    hypothetical_city_obs,
    size_at_horizon,
    tile_output,
)

OBS_FILE = Path("tests/fixtures/real_obs_01.json")

VALS = {
    "W_GROWTH": cfg.W_GROWTH,
    "CITY_POP": cfg.CITY_POP,
    "DOF_SCALE": cfg.DOF_SCALE,
    "FOOD_COST": cfg.FOOD_COST,
    "UNDEPLOYED_CARRIER_SINK_PER_TURN": cfg.UNDEPLOYED_CARRIER_SINK_PER_TURN,
    "SITE_MIN_FOOD": cfg.SITE_MIN_FOOD,
    "SITE_GATE_SIZE": cfg.SITE_GATE_SIZE,
}


def make_map(size: int = 9, fill: tuple[int, int, int] = (0, 0, 0),
             tiles: dict[tuple[int, int], tuple[int, int, int]] | None = None) -> dict:
    """Синтетическая карта: output[x][y] = (еда, щиты, торговля)."""
    out = np.zeros((size, size, 6), dtype=float)
    out[:, :, 0], out[:, :, 1], out[:, :, 2] = fill
    for (x, y), v in (tiles or {}).items():
        out[x, y, 0], out[x, y, 1], out[x, y, 2] = v
    return {"output": out}


class TestRadius:
    def test_area_is_21_tiles_without_corners(self):
        # 21 клетка области влияния ВКЛЮЧАЕТ центр: 20 рабочих смещений + центр.
        assert len(WORKABLE_OFFSETS) == 20
        assert len(WORKABLE_OFFSETS) + 1 == 21
        assert (2, 2) not in WORKABLE_OFFSETS
        assert (2, -2) not in WORKABLE_OFFSETS
        assert (2, 1) in WORKABLE_OFFSETS  # 2²+1² = 5 ≤ radius_sq
        # размер квадрата: все смещения внутри [-2, 2]²
        assert max(max(abs(dx), abs(dy)) for dx, dy in WORKABLE_OFFSETS) == 2

    def test_radius_matches_stand(self):
        assert CITY_RADIUS_SQ == 5


class TestSiteEvaluation:
    def test_best_tiles_are_summed_and_centre_counts_once(self):
        # Центр (4,4) = 3 еды; рядом две клетки 2 и 1 еды. Для size=1 нужны 2 клетки.
        m = make_map(tiles={(4, 4): (3, 0, 0), (3, 4): (2, 0, 0), (5, 4): (1, 0, 0)})
        site = evaluate_site(m, 4, 4, size=1, vals=VALS)
        assert site.food == pytest.approx(5.0)  # 3 + 2, а не только центральная

    def test_size_grows_the_number_of_worked_tiles(self):
        # Все 8 соседей раскрыты (нулевой выход = нераскрытая клетка, поэтому
        # задаём явные значения): центр 3, соседи 2,2,2,1,1,1,1,1.
        neighbours = {
            (3, 4): (2, 0, 0), (5, 4): (2, 0, 0), (4, 3): (2, 0, 0),
            (4, 5): (1, 0, 0), (3, 3): (1, 0, 0), (3, 5): (1, 0, 0),
            (5, 3): (1, 0, 0), (5, 5): (1, 0, 0),
        }
        m = make_map(tiles={(4, 4): (3, 0, 0), **neighbours})
        # size=1 -> центр + 1 житель = 2 лучшие клетки: 3 + 2
        assert evaluate_site(m, 4, 4, size=1, vals=VALS).food == pytest.approx(5.0)
        # size=2 -> центр + 2 жителя = 3 лучшие клетки: 3 + 2 + 2
        assert evaluate_site(m, 4, 4, size=2, vals=VALS).food == pytest.approx(7.0)

    def test_unknown_tiles_are_not_counted_as_zero(self):
        # Единственная известная клетка в радиусе — центр с 2 едой.
        m = make_map(tiles={(4, 4): (2, 0, 0)})
        site = evaluate_site(m, 4, 4, size=1, vals=VALS)
        assert site.known_tiles == 1
        assert site.food == pytest.approx(4.0)   # неизвестные заполнены средним, а не нулём
        assert site.food_low == pytest.approx(2.0)   # нижняя граница — только видимое
        assert site.food_high == pytest.approx(4.0)
        assert site.unknown_ratio > 0.9

    def test_unrevealed_tile_is_recognised_by_zero_output(self):
        m = make_map(tiles={(4, 4): (2, 0, 0)})
        assert tile_output(m, 4, 4)[3] is True
        assert tile_output(m, 0, 0)[3] is False

    def test_map_wraps_in_x(self):
        m = make_map(size=5, tiles={(0, 0): (2, 0, 0)})
        assert tile_output(m, -5, 0)[0] == pytest.approx(2.0)


class TestQualityGate:
    def test_barren_site_is_excised(self):
        m = make_map(tiles={(4, 4): (1, 0, 0)})
        site = evaluate_site(m, 4, 4, size=1, vals=VALS)
        assert site.viable is False
        # С §13.188 годность решает порог ВСТРОЕННОГО ИИ (его `food_starvation`),
        # а не прежний наш `SITE_MIN_FOOD` (§13.166). Причина обязана называть
        # именно его правило — иначе непонятно, чем площадка отвергнута.
        assert "встроенного ИИ" in site.reason
        assert site.starved_food is True

    def test_rich_site_passes(self):
        m = make_map(tiles={(4, 4): (3, 0, 0), (3, 4): (3, 0, 0), (5, 4): (2, 1, 0)})
        site = evaluate_site(m, 4, 4, size=1, vals=VALS)
        assert site.viable is True
        assert site.food >= cfg.SITE_MIN_FOOD


class TestCounterfactualGrowth:
    def test_granary_matches_the_stand_rule(self):
        # rules стенда: амбар = 10 × (size + 1)
        assert growth_box(1) == 20.0
        assert growth_box(2) == 30.0

    def test_citizens_per_turn_decreases_with_size(self):
        assert citizens_per_turn(3.0, 1) == pytest.approx(0.15)
        assert citizens_per_turn(3.0, 2) == pytest.approx(0.10)
        assert citizens_per_turn(-5.0, 1) == 0.0

    def test_founding_earlier_yields_a_bigger_city(self):
        rich = make_map(tiles={(4, 4): (3, 0, 0), (3, 4): (3, 0, 0), (5, 4): (3, 0, 0)})
        site = evaluate_site(rich, 4, 4, size=1, vals=VALS)
        assert site.food_surplus > 0
        later_size, _ = size_at_horizon(site, turns=15, size=1)
        assert later_size > 1  # на 15-м ходу город был бы больше первого размера

    def test_size_at_horizon_is_monotone_in_surplus(self):
        poor = make_map(tiles={(4, 4): (2, 0, 0), (3, 4): (2, 0, 0)})
        rich = make_map(tiles={(4, 4): (3, 0, 0), (3, 4): (3, 0, 0), (5, 4): (3, 0, 0)})
        s_poor = size_at_horizon(evaluate_site(poor, 4, 4, size=1, vals=VALS),
                                 turns=15, size=1)[0]
        s_rich = size_at_horizon(evaluate_site(rich, 4, 4, size=1, vals=VALS),
                                 turns=15, size=1)[0]
        assert s_rich >= s_poor

    def test_sink_floor_when_site_is_unknown(self):
        assert counterfactual_growth_sink_per_turn(None, VALS) == pytest.approx(
            cfg.UNDEPLOYED_CARRIER_SINK_PER_TURN)

    def test_sink_scales_with_the_site(self):
        rich = make_map(tiles={(4, 4): (3, 0, 0), (3, 4): (3, 0, 0), (5, 4): (3, 0, 0)})
        site = evaluate_site(rich, 4, 4, size=1, vals=VALS)
        # surplus = 6 − 2 = 4; 0.35 × 1.0 × 10 × (4 / 20)
        assert site.food_surplus == pytest.approx(4.0)
        assert counterfactual_growth_sink_per_turn(site, VALS) == pytest.approx(0.7)

    def test_sink_beats_the_flat_proxy_on_a_good_site(self):
        rich = make_map(tiles={(4, 4): (3, 0, 0), (3, 4): (3, 0, 0), (5, 4): (3, 0, 0)})
        site = evaluate_site(rich, 4, 4, size=1, vals=VALS)
        rate = counterfactual_growth_sink_per_turn(site, VALS)
        assert rate > cfg.UNDEPLOYED_CARRIER_SINK_PER_TURN


class TestSiteIsPricedWithTheCityFormula:
    """Город на площадке считается той же формулой, что и настоящий город."""

    def _site(self, tiles):
        return evaluate_site(make_map(tiles=tiles), 4, 4, size=1, vals=VALS)

    def test_hypothetical_city_is_a_size_one_capital(self):
        site = self._site({(4, 4): (3, 0, 0), (3, 4): (3, 0, 0), (5, 4): (2, 1, 0)})
        probe = hypothetical_city_obs(site)
        assert probe["size"] == 1
        assert probe["granary_size"] == 20.0          # 10 × (1 + 1)
        assert probe["surplus_food"] == site.food     # валовая еда, как поле стенда
        assert probe["improvements"] == [True]        # бесплатный Palace столицы
        assert hypothetical_city_obs(site, capital=False)["improvements"] == []

    def test_richer_site_prices_a_more_valuable_city(self):
        poor = self._site({(4, 4): (2, 0, 0), (3, 4): (1, 0, 0), (5, 4): (1, 0, 0)})
        rich = self._site({(4, 4): (4, 2, 3), (3, 4): (3, 2, 2), (5, 4): (3, 1, 2)})
        v_poor = city_options(hypothetical_city_obs(poor), garrison=0)
        v_rich = city_options(hypothetical_city_obs(rich), garrison=0)
        assert v_rich > v_poor > 0


class TestFoundingDeltaIsSiteSpecific:
    def _state(self, *, viable: bool) -> SystemStateMatrix:
        bridge = BridgeCalibration(new_city_options=3.0)
        if viable:
            bridge.new_city_options_by_unit["unit_7"] = 9.0
        else:
            bridge.nonviable_carrier_sites.append("unit_7")
        return SystemStateMatrix(
            entities={"unit_7": EntityState(entity_id="unit_7", entity_type="unit",
                                            dof_count=4.0, current_dof=0.4)},
            bridge=bridge,
        )

    def test_delta_uses_the_units_own_site(self):
        action = CivAction(ctrl_type="unit", actor_id=7, action_name="build_city")
        delta = estimate_dof_delta(action, self._state(viable=True))
        # 9.0 (город на ЭТОЙ площадке) − 4.0 (носитель), а не 3.0 из среднего.
        assert delta == {"unit_7": pytest.approx(5.0)}

    def test_nonviable_site_is_excised_not_penalised(self):
        action = CivAction(ctrl_type="unit", actor_id=7, action_name="build_city")
        assert estimate_dof_delta(action, self._state(viable=False)) == {}

    def test_falls_back_to_the_empire_estimate_without_a_site(self):
        bridge = BridgeCalibration(new_city_options=3.0)
        state = SystemStateMatrix(
            entities={"unit_7": EntityState(entity_id="unit_7", entity_type="unit",
                                            dof_count=4.0, current_dof=0.4)},
            bridge=bridge,
        )
        action = CivAction(ctrl_type="unit", actor_id=7, action_name="build_city")
        assert estimate_dof_delta(action, state) == {"unit_7": pytest.approx(-1.0)}


@pytest.mark.skipif(not OBS_FILE.exists(), reason="нет реального наблюдения")
class TestSinkOnRealObservation:
    """Цена задержки растёт с возрастом носителя — на настоящих данных стенда."""

    @pytest.fixture
    def snapshot(self) -> dict:
        with open(OBS_FILE) as f:
            return json.load(f)[0]

    def test_sink_accumulates_and_exceeds_the_flat_proxy(self, snapshot):
        obs, info = snapshot["observation"], snapshot["info"]
        extractor = GameStateExtractor(my_player_id=0)

        first = extractor.extract(obs, info, 1)
        # Тот же экстрактор, шесть ходов спустя: носители «постарели» на 5.
        later = extractor.extract(obs, info, 6)

        assert first.state.dof_sink <= later.state.dof_sink
        world = extractor.model.values()
        vals = dict(world)
        if "rules.food_cost" in vals:
            vals["FOOD_COST"] = vals["rules.food_cost"]
        map_obs = obs.get("map") or {}
        expected_extra = 0.0
        for unit_id, u in (obs.get("unit") or {}).items():
            if not isinstance(u, dict) or not is_population_carrier(u):
                continue
            site = evaluate_site(map_obs, int(u["x"]), int(u["y"]), size=1, vals=vals)
            if site.viable:
                expected_extra += counterfactual_growth_sink_per_turn(site, vals, size=1) * 5
            else:
                expected_extra += vals["UNDEPLOYED_CARRIER_SINK_PER_TURN"] * 5
        assert later.state.dof_sink - first.state.dof_sink == pytest.approx(
            expected_extra, rel=1e-6)
