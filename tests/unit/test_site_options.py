"""Опции площадки: берег и ресурсы (пункт 2).

Берег и ресурсы — не выход клетки, а дополнительные пути развития (гавань,
морские юниты, торговля; ресурс ускоряет рост), поэтому они входят в ценность
города как ОПЦИИ и с потолком. Ресурсность определяется измерением: экстра
считается ресурсом, только если её эффект замерен и не равен нулю.
"""
from __future__ import annotations

import numpy as np
import pytest

from env import config as cfg
from env.site_eval import evaluate_site
from env.terrain_work import terrain_names

TERRAIN_NAMES, EXTRA_NAMES = terrain_names()

VALS = {
    "FOOD_COST": cfg.FOOD_COST,
    "SITE_MIN_FOOD": cfg.SITE_MIN_FOOD,
    "SITE_GATE_SIZE": cfg.SITE_GATE_SIZE,
    "SITE_COAST_BONUS": cfg.SITE_COAST_BONUS,
    "SITE_RESOURCE_BONUS": cfg.SITE_RESOURCE_BONUS,
    "SITE_OPTION_BONUS_CAP": cfg.SITE_OPTION_BONUS_CAP,
    "WATER_TERRAINS": list(cfg.WATER_TERRAINS),
    "MEASURED_EXTRA_EFFECTS": dict(cfg.MEASURED_EXTRA_EFFECTS),
}


def site_map(*, terrain_of=None, extras_of=None, food=2, size=9) -> dict:
    """Карта с явным террейном и экстрами (для берега и ресурсов)."""
    terrain = np.zeros((size, size), dtype=int)
    out = np.zeros((size, size, 6), dtype=float)
    out[:, :, 0] = food
    extras = np.zeros((size, size, len(EXTRA_NAMES)), dtype=bool)
    for (x, y), name in (terrain_of or {}).items():
        terrain[x, y] = TERRAIN_NAMES.index(name)
    for (x, y), names in (extras_of or {}).items():
        for name in names:
            extras[x, y, EXTRA_NAMES.index(name)] = True
    return {"terrain": terrain, "output": out, "extras": extras}


class TestCoast:
    def test_water_in_range_makes_the_site_coastal(self):
        m = site_map(terrain_of={(4, 3): "Ocean"})
        site = evaluate_site(m, 4, 4, size=1, vals=VALS)
        assert site.coastal is True
        assert site.option_bonus == pytest.approx(cfg.SITE_COAST_BONUS)

    def test_inland_site_gets_no_coast_bonus(self):
        m = site_map()
        site = evaluate_site(m, 4, 4, size=1, vals=VALS)
        assert site.coastal is False
        assert site.option_bonus == 0.0

    def test_water_two_tiles_away_still_counts(self):
        # Область города — радиус 2: берег в двух клетках всё ещё даёт гавань.
        m = site_map(terrain_of={(6, 4): "Lake"})
        assert evaluate_site(m, 4, 4, size=1, vals=VALS).coastal is True
        distant = site_map(terrain_of={(9, 4): "Lake"}, size=12)
        assert evaluate_site(distant, 4, 4, size=1, vals=VALS).coastal is False


class TestResources:
    def test_measured_resource_is_an_option(self):
        # Coal измерен на живом стенде => это ресурс.
        m = site_map(extras_of={(4, 3): ["Coal"]})
        site = evaluate_site(m, 4, 4, size=1, vals=VALS)
        assert site.resource_types == ("Coal",)
        assert site.option_bonus == pytest.approx(cfg.SITE_RESOURCE_BONUS)

    def test_unmeasured_extra_is_not_a_resource(self):
        # Irrigation пока не измерена: она НЕ даёт опции (иначе получилось бы
        # правдоподобное число вместо измерения).
        m = site_map(extras_of={(4, 3): ["Irrigation"]})
        site = evaluate_site(m, 4, 4, size=1, vals=VALS)
        assert site.resource_types == ()
        assert site.option_bonus == 0.0

    def test_zero_effect_extra_is_not_a_resource(self):
        m = site_map(extras_of={(4, 3): ["River"]})   # измерено: эффекта нет
        assert evaluate_site(m, 4, 4, size=1, vals=VALS).resource_types == ()

    def test_option_bonus_is_capped(self):
        m = site_map(terrain_of={(3, 4): "Ocean"},
                     extras_of={(4, 3): ["Coal"], (5, 4): ["Silk"], (4, 5): ["Wine"]})
        site = evaluate_site(m, 4, 4, size=1, vals=VALS)
        assert len(site.resource_types) == 3
        assert site.option_bonus == pytest.approx(cfg.SITE_OPTION_BONUS_CAP)

    def test_distinct_types_are_counted_once(self):
        m = site_map(extras_of={(4, 3): ["Coal"], (3, 4): ["Coal"], (5, 4): ["Coal"]})
        site = evaluate_site(m, 4, 4, size=1, vals=VALS)
        assert site.resource_types == ("Coal",)
        assert site.option_bonus == pytest.approx(cfg.SITE_RESOURCE_BONUS)


class TestOptionsReachTheFoundingValue:
    """Опции обязаны попадать в цену основания, а не жить отдельно."""

    def test_coastal_site_prices_higher_than_inland(self):
        from env.entity_extractor import GameStateExtractor

        coastal = {"map": site_map(terrain_of={(3, 4): "Ocean"}),
                   "city": {}, "unit": {"7": {"rule_name": "Settlers", "x": 4, "y": 4,
                                              "type_hp": 20, "health": 20}}}
        inland = {"map": site_map(), "city": {},
                  "unit": {"7": {"rule_name": "Settlers", "x": 4, "y": 4,
                                 "type_hp": 20, "health": 20}}}
        ex = GameStateExtractor(my_player_id=0)
        v_coast = ex.extract(coastal, {}, 1).state.bridge.new_city_options_by_unit.get("unit_7")
        v_inland = ex.extract(inland, {}, 1).state.bridge.new_city_options_by_unit.get("unit_7")
        assert v_coast is not None and v_inland is not None
        assert v_coast > v_inland
        assert v_coast - v_inland == pytest.approx(cfg.SITE_COAST_BONUS)
