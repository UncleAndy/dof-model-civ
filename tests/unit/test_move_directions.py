"""Точная цель `goto_N`: N — это направление dir8, а не «просто имя».

Измерено по исходнику стенда 2026-09-27: `ActGoto.__init__` делает
`action_key = "goto_%i" % dir8`, а команда — `ORDER_MOVE` с тем же dir8 и
`dest_tile = mapstep(ptile, dir8)`. Значит цель хода ВЫЧИСЛИМА, и прежнее
утверждение «координат у goto_N нет» отозвано.

Арифметика направлений — из `map_const.DIR_DX/DIR_DY`; замыкание по X (цилиндр),
по Y — полюс.
"""
from __future__ import annotations

from brain.forecast.live import reach_tiles, direction_target
from brain.forecast.options import Valuations, candidates
from brain.forecast.state import ForecastState

SHAPE = (78, 52)


class TestDirectionTarget:
    def test_eight_directions_from_a_mid_map_tile(self):
        here = (10, 10)
        expected = {
            0: (9, 9),    # СЗ
            1: (10, 9),   # С
            2: (11, 9),   # СВ
            3: (9, 10),   # З
            4: (11, 10),  # В
            5: (9, 11),   # ЮЗ
            6: (10, 11),  # Ю
            7: (11, 11),  # ЮВ
        }
        for dir8, tile in expected.items():
            assert direction_target(here, dir8, SHAPE) == tile, dir8

    def test_x_wraps_like_a_cylinder(self):
        assert direction_target((0, 20), 3, SHAPE) == (77, 20)
        assert direction_target((77, 20), 4, SHAPE) == (0, 20)

    def test_y_has_poles_and_is_not_wrapped(self):
        # Север выше нулевой строки — клетки нет, а не «последняя строка».
        assert direction_target((5, 0), 1, SHAPE) is None
        assert direction_target((5, 0), 0, SHAPE) is None
        assert direction_target((5, 0), 2, SHAPE) is None
        assert direction_target((5, 51), 6, SHAPE) is None
        assert direction_target((5, 51), 5, SHAPE) is None

    def test_diagonal_at_the_pole_is_dropped_entirely(self):
        # СЗ у верхнего края: X замкнулся бы, но Y за краем — значит шага нет.
        assert direction_target((0, 0), 0, SHAPE) is None

    def test_bad_direction_is_not_a_step(self):
        assert direction_target((5, 5), 8, SHAPE) is None
        assert direction_target((5, 5), -1, SHAPE) is None


class TestReachDoesNotWrapY:
    def test_no_tile_from_the_opposite_edge(self):
        tiles = reach_tiles((5, 0), 2, (10, 10))
        assert tiles, "достижимость не пуста"
        assert all(0 <= y < 10 for _x, y in tiles)
        # Чужой край (y = 9) не должен появиться «через полюс».
        assert (5, 9) not in tiles

    def test_x_still_wraps(self):
        tiles = reach_tiles((0, 5), 2, (10, 10))
        assert (9, 5) in tiles or (8, 5) in tiles


def _vals(moves, *, viable=(), reach=()):
    viable_set = set(viable)
    return Valuations(
        reach=lambda _u: list(reach),
        moves=lambda _u: list(moves),
        site_viable=lambda tile: tile in viable_set,
        city_dof=lambda _t: 6.0,
        city_ids=lambda: [],
        productions=lambda _c: [],
        techs=lambda: [],
        works=lambda _t: [],
        is_carrier=lambda _u: True,
        info_gain=lambda _t: 0.0,
    )


class TestExactStepCandidates:
    def _state(self):
        return ForecastState(
            dof={"unit_1": 4.0},
            reversible={"unit_1": True},
            positions={"unit_1": (10, 10)},
            root_dof={"unit_1": 4.0},
            revealed={(10, 10)},
        )

    def test_the_candidate_carries_the_real_direction_name(self):
        vals = _vals([("goto_4", (11, 10)), ("goto_1", (10, 9))],
                     viable={(11, 10)})
        moves = [c for c in candidates(self._state(), vals) if c.kind == "move"]
        assert len(moves) == 1
        assert moves[0].action == ("unit", "unit_1", "goto_4")
        assert moves[0].extra["tile"] == (11, 10)

    def test_only_offered_directions_become_steps(self):
        # Годных клеток рядом две, но сервер предложил только одну команду.
        vals = _vals([("goto_1", (10, 9))], viable={(10, 9), (11, 10)})
        moves = [c for c in candidates(self._state(), vals) if c.kind == "move"]
        assert [c.action[2] for c in moves] == ["goto_1"]

    def test_a_step_into_a_worthless_tile_is_not_offered(self):
        vals = _vals([("goto_4", (11, 10))], viable=set())
        assert [c for c in candidates(self._state(), vals) if c.kind == "move"] == []

    def test_without_a_menu_the_family_path_is_used(self):
        vals = Valuations(
            reach=lambda _u: [(10, 10), (12, 10)],
            site_viable=lambda tile: tile == (12, 10),
            city_dof=lambda _t: 6.0,
            city_ids=lambda: [],
            productions=lambda _c: [],
            techs=lambda: [],
            works=lambda _t: [],
            is_carrier=lambda _u: True,
        )
        moves = [c for c in candidates(self._state(), vals) if c.kind == "move"]
        assert moves and moves[0].action[2] == "goto"
        assert moves[0].extra["tile"] == (12, 10)
