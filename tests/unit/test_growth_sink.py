"""Цена задержки по формуле города (пункт 3).

Раньше рост оценивался плоским «житель = CITY_POP × DOF_SCALE». Теперь цена —
прирост ценности города, посчитанной ТОЙ ЖЕ формулой, что и настоящий город:
размер входит и в базу, и в амбар, а множители площадки (еда, щиты, торговля,
бесплатный Palace столицы) влияют на неё.
"""
from __future__ import annotations

import numpy as np
import pytest

from env import config as cfg
from env.entity_extractor import GameStateExtractor
from env.site_eval import (
    counterfactual_growth_sink,
    counterfactual_growth_sink_per_turn,
    evaluate_site,
    size_at_horizon,
)

VALS = {
    "W_GROWTH": cfg.W_GROWTH,
    "CITY_POP": cfg.CITY_POP,
    "DOF_SCALE": cfg.DOF_SCALE,
    "FOOD_COST": cfg.FOOD_COST,
    "GROWTH_HORIZON_TURNS": cfg.GROWTH_HORIZON_TURNS,
    "UNDEPLOYED_CARRIER_SINK_PER_TURN": cfg.UNDEPLOYED_CARRIER_SINK_PER_TURN,
    "SITE_MIN_FOOD": cfg.SITE_MIN_FOOD,
    "SITE_GATE_SIZE": cfg.SITE_GATE_SIZE,
}


def make_map(size: int = 12, fill=(3, 0, 0), tiles=None) -> dict:
    out = np.zeros((size, size, 6), dtype=float)
    out[:, :, 0], out[:, :, 1], out[:, :, 2] = fill
    for (x, y), v in (tiles or {}).items():
        out[x, y, 0], out[x, y, 1], out[x, y, 2] = v
    return {"output": out}


class TestGrowthSinkFormula:
    def _site(self, fill=(3, 0, 0)):
        return evaluate_site(make_map(fill=fill), 5, 5, size=1, vals=VALS)

    def test_sink_is_the_growth_gain_per_turn(self):
        site = self._site()
        # Ценность города растёт с размером: это и есть проверяемая величина.
        value_of_size = lambda s: 10.0 + 3.0 * s  # noqa: E731
        sink = counterfactual_growth_sink(site, VALS, value_of_size, size=1)
        grown, _ = size_at_horizon(site, turns=VALS["GROWTH_HORIZON_TURNS"], size=1)
        assert grown > 1
        expected = cfg.W_GROWTH * (value_of_size(grown) - value_of_size(1)) \
            / VALS["GROWTH_HORIZON_TURNS"]
        assert sink == pytest.approx(expected)

    def test_floor_applies_when_the_site_is_not_usable(self):
        # Площадка не проходит гейт: расти здесь нечему, терять нечего => пол.
        site = evaluate_site(make_map(fill=(1, 0, 0)), 5, 5, size=1, vals=VALS)
        assert site.viable is False
        assert counterfactual_growth_sink(site, VALS, lambda s: 10.0 * s) == \
            pytest.approx(cfg.UNDEPLOYED_CARRIER_SINK_PER_TURN)

    def test_a_site_that_passes_the_gate_always_grows(self):
        # Гейт (6 еды на 3 клетках) строже роста (положительный излишек после
        # еды жителей), поэтому у годной площадки терять всегда есть что: пол
        # остаётся только для неоценённой или негодной площадки. Это свойство,
        # а не совпадение — и оно делает «город-однодневку» невозможным.
        site = evaluate_site(make_map(fill=(2, 0, 0)), 5, 5, size=1, vals=VALS)
        assert site.viable is True
        grown, _ = size_at_horizon(site, turns=VALS["GROWTH_HORIZON_TURNS"], size=1)
        assert grown > 1
        assert counterfactual_growth_sink(site, VALS, lambda s: 10.0 * s) > \
            cfg.UNDEPLOYED_CARRIER_SINK_PER_TURN

    def test_missing_site_falls_back_to_the_floor(self):
        assert counterfactual_growth_sink(None, VALS, lambda s: 99.0) == \
            pytest.approx(cfg.UNDEPLOYED_CARRIER_SINK_PER_TURN)

    def test_flat_proxy_is_larger_than_the_city_formula(self):
        # Плоский прокси завышает: он берёт CITY_POP × DOF_SCALE = 10 опций за
        # жителя, тогда как настоящий город размера 1 стоит ~8 опций целиком.
        site = self._site()
        proxy = counterfactual_growth_sink_per_turn(site, VALS, size=1)
        # Ценность города растёт с размером примерно как база + житель × множители.
        formula = counterfactual_growth_sink(site, VALS, lambda s: 7.0 + 2.6 * s)
        assert formula < proxy
        assert formula >= cfg.UNDEPLOYED_CARRIER_SINK_PER_TURN


class TestExtractorUsesTheFormula:
    def _obs(self, x=5, y=5):
        return {
            "map": make_map(tiles={(5, 5): (3, 0, 0)}),
            "city": {},
            "unit": {"7": {"rule_name": "Settlers", "x": x, "y": y,
                           "type_hp": 20, "health": 20, "type_move_rate": 1}},
        }

    def test_sink_grows_with_age_and_matches_the_formula(self):
        ex = GameStateExtractor(my_player_id=0)
        obs = self._obs()
        ex.extract(obs, {}, 1)              # носитель впервые замечен на ходу 1
        later = ex.extract(obs, {}, 6)      # возраст 5
        vals = dict(ex.model.values())
        if "rules.food_cost" in vals:
            vals["FOOD_COST"] = vals["rules.food_cost"]
        site = evaluate_site(obs["map"], 5, 5, size=1, vals=vals)
        given = site.viable
        assert given
        rate = counterfactual_growth_sink(
            site, vals, lambda s: ex._site_city_value_at(site, True, s), size=1)
        assert later.state.dof_sink == pytest.approx(5 * rate)
        # И это МЕНЬШЕ плоского прокси — то есть риск завышения устранён.
        assert rate < counterfactual_growth_sink_per_turn(site, vals, size=1)
