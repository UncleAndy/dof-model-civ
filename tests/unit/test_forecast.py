"""Решающие тесты прогноза: последствия, вето, дисконт, «не действовать».

Главный из них — `test_walk_then_found`: поселенец, у которого ВСЕ сегодняшние
дельты нулевые, а в трёх клетках есть годная площадка. Прежний поиск перебирал
«нынешнее меню, повторённое N раз» и в этом случае замерзал (измерено на стенде:
0 решений за 50 ходов). Настоящий прогноз обязан увидеть, что ход открывает
основание города, и пойти.

Шкала — ЧИСЛО ОПЦИЙ (живая сущность ≥ 1), потому что индекс считается как
`Σ ln(DoF)`: при нормализованных долях логарифм отрицателен, добавление города
«ухудшает» индекс и правило «строго > 0» запрещает действовать. Это не мелочь
теста: на этой ошибке уже спотыкался проект.
"""
from __future__ import annotations

import math

import pytest

from brain.forecast import (
    FORECAST_GAMMA,
    ForecastState,
    Valuations,
    candidates,
    choose,
)

CARRIER_OPTIONS = 3.0     # поселенец: три пути развития (основать, работать, идти)
CITY_OPTIONS = 6.0        # город размера 1: заметно больше опций, чем у носителя


def _base_state(**kw) -> ForecastState:
    state = ForecastState(
        dof={"unit_1": CARRIER_OPTIONS},
        reversible={"unit_1": True},
        positions={"unit_1": (0, 0)},
        root_dof={"unit_1": CARRIER_OPTIONS},
        revealed={(0, 0)},
    )
    for key, value in kw.items():
        setattr(state, key, value)
    return state


def _vals(*, viable_tiles=(), city_options=CITY_OPTIONS, reach_tiles=(),
          works=(), productions=(), techs=(), info=0.0) -> Valuations:
    viable = set(viable_tiles)
    return Valuations(
        reach=lambda _unit: list(reach_tiles),
        site_viable=lambda tile: tile in viable,
        city_dof=lambda _tile: city_options,
        city_ids=lambda: [],
        productions=lambda _city: list(productions),
        techs=lambda: list(techs),
        works=lambda _tile: list(works),
        is_carrier=lambda _unit: True,
        info_gain=lambda _tile: info,
    )


class TestWalkThenFound:
    """«Идти → встать на площадку → основать» — то, что прежний поиск не видел."""

    def test_the_agent_walks_when_only_the_successor_has_value(self):
        vals = _vals(
            viable_tiles={(3, 0)},
            city_options=CITY_OPTIONS,
            reach_tiles=[(0, 0), (1, 0), (2, 0), (3, 0)],
        )
        choice = choose(_base_state(), vals, horizon=3, beam=3)
        assert choice.action == ("unit", "unit_1", "goto")
        assert choice.value > 0
        # Ценность приходит не от хода, а от того, что он открывает.
        assert choice.path[0][2].startswith("goto")

    def test_the_destination_is_the_viable_site(self):
        vals = _vals(
            viable_tiles={(3, 0)},
            reach_tiles=[(0, 0), (1, 0), (2, 0), (3, 0)],
        )
        moves = [c for c in candidates(_base_state(), vals) if c.kind == "move"]
        assert len(moves) == 1
        assert moves[0].extra["tile"] == (3, 0)

    def test_the_successor_offers_founding_where_there_was_none(self):
        # Перевывод возможностей: на старом месте основания нет, на новом — есть.
        vals = _vals(viable_tiles={(3, 0)},
                     reach_tiles=[(0, 0), (1, 0), (2, 0), (3, 0)])
        state = _base_state()
        assert [c for c in candidates(state, vals) if c.kind == "found"] == []
        move = next(c for c in candidates(state, vals) if c.kind == "move")
        after_move = move.effect.state
        assert [c for c in candidates(after_move, vals) if c.kind == "found"]

    def test_with_beam_one_the_walk_survives_pruning(self):
        # У хода нулевой немедленный эффект: срезать ветви «по дельте» значило бы
        # потерять основание города. Порядок ветвления обязан учитывать преемника.
        vals = _vals(viable_tiles={(3, 0)},
                     reach_tiles=[(0, 0), (1, 0), (2, 0), (3, 0)])
        choice = choose(_base_state(), vals, horizon=3, beam=1)
        assert choice.action == ("unit", "unit_1", "goto")


class TestNoImprovement:
    """«Нет строгого улучшения — не действовать» сохраняется."""

    def test_no_viable_site_anywhere_means_no_action(self):
        vals = _vals(viable_tiles=set(), reach_tiles=[(0, 0), (1, 0), (2, 0)])
        choice = choose(_base_state(), vals)
        assert choice.action is None
        assert "нет строгого улучшения" in choice.reason

    def test_a_move_into_a_worthless_tile_is_not_offered(self):
        vals = _vals(viable_tiles=set(), reach_tiles=[(0, 0), (1, 0)])
        assert [c for c in candidates(_base_state(), vals) if c.kind == "move"] == []


class TestVetoAndPenalty:
    """Вето Аксиомы 3: ветвь, где обратимая сущность ушла в коллапс, отбрасывается."""

    def test_a_collapsing_branch_is_dropped(self):
        state = ForecastState(
            dof={"city_1": 5.0, "unit_1": CARRIER_OPTIONS},
            reversible={"city_1": True, "unit_1": True},
            positions={"unit_1": (0, 0)},
            cities={"city_1": (0, 0)},
            root_dof={"city_1": 5.0, "unit_1": CARRIER_OPTIONS},
        )
        vals = _vals(viable_tiles=set(), reach_tiles=[(0, 0)],
                     works=[("mine", -5.0, "city_1")])
        choice = choose(state, vals, horizon=1, beam=3)
        assert choice.action is None

    def test_an_irreversible_action_pays_a_penalty(self):
        state = _base_state()
        vals = _vals(viable_tiles=set(), reach_tiles=[(0, 0)],
                     techs=[("tech_9", 1.2, 0)])
        # ln(1.2) = +0.182, штраф 0.2 — ветвь уходит в минус: действовать не надо.
        choice = choose(state, vals, horizon=1, beam=3, irreversible_penalty=0.2)
        assert choice.action is None

    def test_the_same_action_wins_without_the_penalty(self):
        state = _base_state()
        vals = _vals(viable_tiles=set(), reach_tiles=[(0, 0)],
                     techs=[("tech_9", 1.2, 0)])
        choice = choose(state, vals, horizon=1, beam=3, irreversible_penalty=0.0)
        assert choice.action is not None


class TestDiscount:
    """Дальняя выгода весомее нуля, но меньше ближней."""

    def _two_ways(self):
        state = ForecastState(
            dof={"unit_1": CARRIER_OPTIONS, "city_1": 4.0},
            reversible={"unit_1": True, "city_1": False},
            positions={"unit_1": (0, 0)},
            cities={"city_1": (0, 0)},
            root_dof={"unit_1": CARRIER_OPTIONS, "city_1": 4.0},
        )
        vals = Valuations(
            reach=lambda _u: [(0, 0)],
            site_viable=lambda _t: False,
            city_dof=lambda _t: 0.0,
            city_ids=lambda: ["city_1"],
            # Быстро: ln(3) = 1.10 сейчас. Долго: ln(20) = 3.00 через пять ходов,
            # то есть 3.00 × 0.8⁵ = 0.98 — меньше.
            productions=lambda _c: [("Fast", 3.0, 0)],
            techs=lambda: [("slow", 20.0, 5)],
            works=lambda _t: [],
            is_carrier=lambda _u: False,
        )
        return state, vals

    def test_a_payoff_five_turns_out_is_discounted(self):
        state, vals = self._two_ways()
        choice = choose(state, vals, horizon=1, beam=3, irreversible_penalty=0.0,
                        gamma=FORECAST_GAMMA)
        assert choice.best_candidate is not None
        assert choice.best_candidate.extra.get("type") == "Fast"

    def test_without_discounting_the_larger_payoff_wins(self):
        state, vals = self._two_ways()
        choice = choose(state, vals, horizon=1, beam=3, irreversible_penalty=0.0,
                        gamma=1.0)
        assert choice.best_candidate is not None
        assert choice.best_candidate.kind == "research"


class TestState:
    def test_index_is_a_product_of_options(self):
        state = ForecastState(dof={"a": 2.0, "b": 4.0})
        assert state.index() == pytest.approx(math.log(2.0) + math.log(4.0))

    def test_a_collapse_source_does_not_count(self):
        state = ForecastState(dof={"a": 3.0, "b": 0.0},
                              collapse_sources={"b"})
        assert state.index() == pytest.approx(math.log(3.0))

    def test_collapsed_reports_only_reversible_losses(self):
        state = ForecastState(
            dof={"u": 0.0, "c": 0.0},
            reversible={"u": True, "c": False},
            root_dof={"u": 3.0, "c": 9.0},
        )
        assert state.collapsed() == ["u"]

    def test_a_healthy_entity_never_collapses(self):
        state = ForecastState(
            dof={"u": CARRIER_OPTIONS},
            reversible={"u": True},
            root_dof={"u": CARRIER_OPTIONS},
        )
        assert state.collapsed() == []
