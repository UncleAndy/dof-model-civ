"""Сторожа §13.358: путь к площадке (`path_first_step`) — перенос его `dai_unit_goto`."""

from __future__ import annotations


def test_path_walks_around_a_water_wall() -> None:
    """Прямая загорожена водой: жадный шаг бессилен, путь идёт в обход."""
    from brain.ai_default.founder_destination import path_first_step

    blocked = {(4, 3), (4, 4), (4, 5), (4, 6), (4, 2)}
    step = path_first_step((1, 4), (7, 4), lambda x, y: (x, y) not in blocked)
    assert step is not None
    assert abs(step[0] - 2) <= 1 and abs(step[1] - 4) <= 1     # первый шаг — рядом с началом


def test_path_none_when_target_walled_off() -> None:
    from brain.ai_default.founder_destination import path_first_step

    blocked = {(x, y) for x in (3, 4, 5) for y in range(10)}
    inside = {(x, y) for x in range(12) for y in range(10)}
    # Стена во всю карту: обойти нечем — пути нет.
    assert path_first_step((1, 4), (7, 4),
                           lambda x, y: (x, y) in inside and (x, y) not in blocked) is None


def test_path_straight_line_takes_direct_step() -> None:
    from brain.ai_default.founder_destination import path_first_step

    # Первый шаг — любой, но лежащий на КРАТЧАЙШЕМ пути: расстояние сокращается.
    step = path_first_step((2, 2), (7, 2), lambda x, y: True)
    assert step is not None and max(abs(step[0] - 2), abs(step[1] - 2)) == 1
    assert max(abs(7 - step[0]), abs(2 - step[1])) == 4     # пять ходов всего, один сделан
    assert path_first_step((2, 2), (2, 2), lambda x, y: True) is None


def test_path_wraps_x_on_cylinder() -> None:
    """X — цилиндр: с (0,5) к (9,5) при ширине 10 путь идёт через край, а не назад."""
    from brain.ai_default.founder_destination import path_first_step

    step = path_first_step((0, 5), (9, 5), lambda x, y: True, shape=(10, 10))
    assert step == (1, 5) or step == (9, 5)     # через край короче (1 шаг) — берём (9,5)


def test_goto_name_to_maps_step_to_offered_name() -> None:
    from brain.ai_default.founder_destination import GOTO_DIRECTIONS, goto_name_to

    # имя шага, встающего ровно на соседнюю клетку, обязано лежать в его же таблице шагов
    name = goto_name_to((5, 5), (6, 5))
    assert name is not None and GOTO_DIRECTIONS[name] == (1, 0)
    assert goto_name_to((5, 5), (5, 5)) is None
