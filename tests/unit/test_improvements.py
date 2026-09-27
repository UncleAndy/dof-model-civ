"""Улучшения как ОТДЕЛЬНОЕ семейство: растут опции города, а не число сущностей.

Почему это отдельная ветка, а не «ещё один вид производства»: юнит — новая живая
сущность со своим набором возможностей (слагаемое в `Σ ln DoF`), здание — нет.
Здание расширяет то, что может делать ГОРОД, поэтому прибавка идёт к опциям
города (`index_delta`). Если считать здание сущностью, его вклад удваивается:
один раз как сущность, второй — через множитель города, куда оно тоже входит.
"""
from __future__ import annotations

import math

import pytest

from brain.forecast.options import Valuations, candidates
from brain.forecast.state import ForecastState
from brain.forecast.transitions import improve


def _state():
    return ForecastState(
        dof={"city_1": 8.0},
        reversible={"city_1": True},
        positions={},
        cities={"city_1": (3, 3)},
        root_dof={"city_1": 8.0},
    )


def _vals(improvements=(), productions=()):
    return Valuations(
        reach=lambda _u: [],
        moves=lambda _u: [],
        site_viable=lambda _t: False,
        city_dof=lambda _t: 0.0,
        city_ids=lambda: ["city_1"],
        productions=lambda _c: list(productions),
        techs=lambda: [],
        works=lambda _t: [],
        is_carrier=lambda _u: False,
        improvements=lambda _c: list(improvements),
    )


class TestImproveTransition:
    def test_it_raises_the_citys_own_options(self):
        state = _state()
        effect = improve(state, "city_1", gain=2.0, turns=0)
        assert state.dof["city_1"] == 8.0                    # исходное не тронуто
        assert effect.state.dof["city_1"] == 10.0
        assert effect.delta == pytest.approx(math.log(10.0) - math.log(8.0))
        assert effect.delta > 0.0

    def test_it_adds_no_new_entity(self):
        state = _state()
        effect = improve(state, "city_1", gain=1.0)
        assert set(effect.state.dof) == {"city_1"}
        assert set(effect.state.root_dof) == {"city_1"}

    def test_a_building_is_an_irreversible_investment(self):
        assert improve(_state(), "city_1", gain=1.0).reversible is False

    def test_the_turns_are_carried_as_a_delay(self):
        assert improve(_state(), "city_1", gain=1.0, turns=4).delay == 4

    def test_an_unknown_city_is_left_alone(self):
        assert improve(_state(), "city_9", gain=1.0).delta == 0.0


class TestImproveCandidates:
    def test_the_improvement_appears_as_its_own_kind(self):
        vals = _vals(improvements=[("Temple", 2.0, 3)])
        found = [c for c in candidates(_state(), vals) if c.kind == "improve"]
        assert len(found) == 1
        assert found[0].action == ("city", "city_1", "produce_Temple")
        assert found[0].effect.delay == 3
        assert found[0].extra["gain"] == 2.0

    def test_units_and_improvements_stay_separate_families(self):
        vals = _vals(improvements=[("Temple", 2.0, 3)],
                     productions=[("Warriors", 4.5, 2)])
        kinds = sorted(c.kind for c in candidates(_state(), vals))
        assert kinds == ["improve", "produce"]

    def test_no_improvements_offered_means_no_candidates(self):
        # Гейт «улучшение ничего не добавляет → не предлагать» живёт у провода
        # (`live.improvements`: gain ≤ 0 пропускается), потому что только там
        # видна формула города и её потолок. Здесь проверяется, что пустой набор
        # не превращается в кандидата сам собой.
        vals = _vals(improvements=[])
        assert [c for c in candidates(_state(), vals) if c.kind == "improve"] == []
