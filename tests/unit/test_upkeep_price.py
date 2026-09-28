"""V3-1: цена содержания юнитов (§10.35) — из формулы города, и только своя.

Проверяется ровно то, что объявлено:
* содержание ЧУЖИХ юнитов в наш сток не попадает (найденный дефект);
* цена пункта содержания берётся ЖИВО с записи нашего города (формула города), а не
  плоским весом 0.05;
* если города в наблюдении нет — работает запасной плоский вес;
* юнит без поля владельца считается своим (иначе страдали бы синтетические наблюдения).
"""
import json
from pathlib import Path

import pytest

from env.config import UNIT_UPKEEP_SINK_W
from env.entity_extractor import GameStateExtractor, city_options

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "real_obs_01.json"


def _real_city() -> dict:
    """Реальная запись города из сохранённого наблюдения — не выдуманная."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    obs = raw[0]["observation"] if isinstance(raw, list) else raw
    _cid, rec = next(iter(obs["city"].items()))
    return dict(rec)


def _unit(**fields) -> dict:
    base = {"rule_name": "Warriors", "x": 5, "y": 5, "type_hp": 20, "health": 20,
            "type_move_rate": 1}
    base.update(fields)
    return base


def _sink(obs: dict) -> float:
    ex = GameStateExtractor(my_player_id=0)
    return float(ex.extract(obs, {}, 1).state.dof_sink)


class TestOwnUpkeepOnly:
    def test_foreign_upkeep_is_not_our_sink(self):
        obs = {"map": {}, "city": {},
               "unit": {"1": _unit(owner=0, upkeep_gold=1),
                        "2": _unit(owner=3, upkeep_gold=5)}}
        # Свой юнит: 1 × плоский вес. Чужой не считается вовсе.
        assert _sink(obs) == pytest.approx(UNIT_UPKEEP_SINK_W * 1)

    def test_unit_without_owner_counts_as_ours(self):
        obs = {"map": {}, "city": {},
               "unit": {"1": _unit(upkeep_gold=2)}}
        assert _sink(obs) == pytest.approx(UNIT_UPKEEP_SINK_W * 2)

    def test_all_three_fields_are_summed(self):
        obs = {"map": {}, "city": {},
               "unit": {"1": _unit(upkeep_food=1, upkeep_gold=2, upkeep_shield=3)}}
        assert _sink(obs) == pytest.approx(UNIT_UPKEEP_SINK_W * 6)


class TestLivePriceFromTheCity:
    def test_price_comes_from_the_city_formula_and_is_bigger_than_the_flat_weight(self):
        city = _real_city()
        base = float(city_options(city, model=None))
        shifted = dict(city)
        shifted["surplus_gold"] = float(city["surplus_gold"]) + 1.0
        price_gold = float(city_options(shifted, model=None)) - base
        assert price_gold > UNIT_UPKEEP_SINK_W, (
            "живая цена золота должна быть заметно выше плоского веса 0.05")
        obs = {"map": {}, "city": {str(city.get("id", 131)): city},
               "unit": {"1": _unit(owner=0, upkeep_gold=1)}}
        assert _sink(obs) == pytest.approx(price_gold, rel=1e-6)

    def test_foreign_city_does_not_set_our_price(self):
        # Чужой город не должен задавать цену нашему содержанию: остаётся запасной вес.
        city = _real_city()
        city["owner"] = 4
        obs = {"map": {}, "city": {str(city.get("id", 131)): city},
               "unit": {"1": _unit(owner=0, upkeep_gold=1)}}
        assert _sink(obs) == pytest.approx(UNIT_UPKEEP_SINK_W * 1)

    def test_carrier_delay_still_works_with_live_price(self):
        # Задержка населения (второй сток) не должна теряться при новой цене.
        city = _real_city()
        obs = {"map": {}, "city": {str(city.get("id", 131)): city},
               "unit": {"1": {"rule_name": "Settlers", "x": 5, "y": 5, "owner": 0,
                              "type_hp": 20, "health": 20, "type_move_rate": 1}}}
        ex = GameStateExtractor(my_player_id=0)
        ex.extract(obs, {}, 1)
        later = float(ex.extract(obs, {}, 6).state.dof_sink)
        assert later > 0.0