"""V2: шаг юнита несёт долю сохраняемой стоимости (§10.38).

Проверяется ровно объявленное: дельта хода = раскрытие + прогресс; прогресс приходит
из `goal_credit` (доля `R / N`); шаг БЕЗ цели остаётся нулевым и по-прежнему
отбрасывается, если клетка дешевле текущей; расстояние считается по цилиндру.
"""
from __future__ import annotations

import pytest

from brain.forecast.live import _wrap_distance
from brain.forecast.options import Valuations, candidates
from brain.forecast.state import ForecastState
from brain.forecast.transitions import move


def _state():
    return ForecastState(
        dof={"unit_1": 4.0},
        reversible={"unit_1": True},
        positions={"unit_1": (10, 10)},
        root_dof={"unit_1": 4.0},
        revealed={(10, 10)},
    )


def _vals(moves, *, viable=(), goal_credit=None, info_gain=0.0):
    viable_set = set(viable)
    return Valuations(
        reach=lambda _u: [],
        moves=lambda _u: list(moves),
        site_viable=lambda tile: tile in viable_set,
        city_dof=lambda _t: 6.0,
        city_ids=lambda: [],
        productions=lambda _c: [],
        techs=lambda: [],
        works=lambda _t: [],
        is_carrier=lambda _u: True,
        goal_credit=goal_credit,
        info_gain=lambda _t: info_gain,
    )


class TestMoveEffect:
    def test_progress_alone_gives_the_step_a_delta(self):
        effect = move(_state(), "unit_1", (11, 10), info_gain=0.0, progress=0.6)
        assert effect.delta == pytest.approx(0.6)

    def test_progress_adds_to_the_reveal_gain(self):
        effect = move(_state(), "unit_1", (11, 10), info_gain=0.4, progress=0.6)
        assert effect.delta == pytest.approx(1.0)

    def test_negative_progress_is_not_a_gain(self):
        effect = move(_state(), "unit_1", (11, 10), progress=-1.0)
        assert effect.delta == 0.0

    def test_the_note_names_the_progress(self):
        effect = move(_state(), "unit_1", (11, 10), progress=0.25)
        assert "прогресс" in effect.note


class TestCandidatesUseTheCredit:
    def test_a_step_toward_the_goal_survives_a_cheaper_tile(self):
        # Клетка не годна под город (дешевле текущей), но шаг ВЕДЁТ к цели:
        # именно это и делает движение участником ветвления.
        vals = _vals([("goto_4", (11, 10))], viable=set(),
                     goal_credit=lambda _u, _h, _t: 0.6)
        steps = [c for c in candidates(_state(), vals) if c.kind == "move"]
        assert len(steps) == 1
        assert steps[0].action == ("unit", "unit_1", "goto_4")
        assert steps[0].effect.delta == pytest.approx(0.6)
        assert steps[0].extra["progress"] == pytest.approx(0.6)

    def test_a_step_without_a_goal_is_still_dropped(self):
        vals = _vals([("goto_4", (11, 10))], viable=set(), goal_credit=None)
        assert [c for c in candidates(_state(), vals) if c.kind == "move"] == []

    def test_a_goal_credit_of_zero_does_not_change_anything(self):
        vals = _vals([("goto_4", (11, 10))], viable=set(),
                     goal_credit=lambda _u, _h, _t: 0.0)
        assert [c for c in candidates(_state(), vals) if c.kind == "move"] == []

    def test_progress_is_added_on_top_of_the_value_difference(self):
        # Сравнение с тем же кандидатом БЕЗ кредита: прогресс добавляется к подсказке
        # и к дельте, а не заменяет разницу ценности клеток.
        def step(**kwargs):
            vals = _vals([("goto_4", (11, 10))], viable={(11, 10)}, **kwargs)
            return [c for c in candidates(_state(), vals) if c.kind == "move"][0]

        plain = step()
        credited = step(goal_credit=lambda _u, _h, _t: 0.5)
        assert credited.score_hint == pytest.approx(plain.score_hint + 0.5, rel=1e-6)
        assert credited.effect.delta == pytest.approx(plain.effect.delta + 0.5, rel=1e-6)


class TestWrapDistance:
    def test_x_wraps_like_a_cylinder(self):
        assert _wrap_distance((0, 5), (9, 5), (10, 10)) == 1
        assert _wrap_distance((9, 5), (0, 5), (10, 10)) == 1

    def test_y_does_not_wrap(self):
        assert _wrap_distance((5, 0), (5, 9), (10, 10)) == 9

    def test_distance_is_chebyshev_on_the_cylinder(self):
        assert _wrap_distance((1, 1), (3, 4), (10, 10)) == 3

    def test_without_a_shape_x_does_not_wrap(self):
        assert _wrap_distance((0, 5), (9, 5), None) == 9