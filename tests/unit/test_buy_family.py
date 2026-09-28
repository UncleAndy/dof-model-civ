"""Покупка производства: тот же предмет, но без ожидания.

Зачем семейство: прогноз дисконтирует вклад по сроку, поэтому длинные постройки для
него почти бесценны (Settlers при 12 ходах — это γ¹² ≈ 0.07), а прежний путь просто
платит золотом и получает результат сейчас. Цена золота ИЗМЕРЕНА: уходит ровно
`buy_cost` (три точных наблюдения, §10.25.1). Золото в модели больше нигде не оценено,
поэтому единственное ограничение — доступность, и она проверяется у провода.

Здесь проверяется ровно одно: кандидат покупки отличается от производства ТОЛЬКО
задержкой, и по умолчанию (когда провода нет) семейства не появляется вовсе.
"""
from __future__ import annotations

import math

from brain.forecast import transitions as tr
from brain.forecast.options import Valuations, candidates
from brain.forecast.state import ForecastState


def _state(city_id="city_121", dof=6.0):
    state = ForecastState()
    state.dof[city_id] = dof
    state.positions = {}
    return state


def _vals(**over):
    base = dict(
        reach=lambda _u: [],
        site_viable=lambda _t: False,
        city_dof=lambda _t: 0.0,
        city_ids=lambda: ["city_121"],
        productions=lambda city: [("Settlers", 3.81, 12)],
        improvements=lambda city: [],
        techs=lambda: [],
        works=lambda unit_id: [],
        is_carrier=lambda _u: False,
        info_gain=lambda _t: 0.0,
        allowed=lambda *_a: True,
    )
    base.update(over)
    return Valuations(**base)


class TestBuyFamily:
    def test_a_buy_carries_the_same_item_with_no_delay(self):
        vals = _vals(buys=lambda city: [("city_buy_production", "Settlers", 3.81, 22.0)])
        found = [c for c in candidates(_state(), vals) if c.kind == "buy"]
        assert len(found) == 1
        cand = found[0]
        assert cand.action == ("city", "city_121", "city_buy_production")
        assert cand.effect.delay == 0                      # завершается сейчас
        assert abs(cand.effect.delta - math.log(3.81)) < 1e-9
        assert cand.extra["type"] == "Settlers"
        assert cand.extra["gold"] == 22.0

    def test_a_buy_beats_its_own_production_because_of_the_delay_alone(self):
        vals = _vals(buys=lambda city: [("city_buy_production", "Settlers", 3.81, 22.0)])
        kinds = {}
        for cand in candidates(_state(), vals):
            kinds.setdefault(cand.kind, cand)
        buy, produce = kinds["buy"], kinds["produce"]
        # Вклад в индексе один и тот же, различие — только срок.
        assert abs(buy.effect.delta - produce.effect.delta) < 1e-9
        assert produce.effect.delay == 12 and buy.effect.delay == 0
        gamma = 0.8
        assert buy.effect.delta * gamma ** buy.effect.delay > \
            produce.effect.delta * gamma ** produce.effect.delay

    def test_without_a_wire_the_family_does_not_appear(self):
        vals = _vals()                                     # buys не задан
        assert [c for c in candidates(_state(), vals) if c.kind == "buy"] == []

    def test_the_wire_decides_whether_the_buy_is_allowed(self):
        vals = _vals(buys=lambda city: [("city_buy_production", "Settlers", 3.81, 22.0)],
                     allowed=lambda kind, *_a: kind != "buy")
        assert [c for c in candidates(_state(), vals) if c.kind == "buy"] == []

    def test_an_already_decided_city_is_skipped(self):
        vals = _vals(buys=lambda city: [("city_buy_production", "Settlers", 3.81, 22.0)],
                     excluded=lambda ctrl, actor: ctrl == "city")
        assert [c for c in candidates(_state(), vals) if c.kind == "buy"] == []


class TestBuyTransitionMatchesProduce:
    def test_delay_is_the_only_difference(self):
        state = _state()
        made = tr.produce(state, "city_121", unit_id="city_121:Settlers",
                          unit_dof=3.81, turns=12)
        bought = tr.produce(state, "city_121", unit_id="city_121:Settlers",
                            unit_dof=3.81, turns=0)
        assert made.delta == bought.delta
        assert (made.delay, bought.delay) == (12, 0)
        assert made.reversible is False and bought.reversible is False
