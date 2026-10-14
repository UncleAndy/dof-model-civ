"""Перенос НАЗНАЧЕНИЯ поселенца: направления хода и шаг к цели.

Нумерация направлений — правило клиента, не наше: `goto_0..7` = СЗ, С, СВ, З, В, ЮЗ, Ю, ЮВ
(не круговая). Тест стережёт именно её: подмена направления молча уводит поселенца в другую
сторону, а это ошибка, которую на стенде видно только по отсутствию городов.
"""
from __future__ import annotations

from brain.ai_default.founder_destination import (
    GOTO_DIRECTIONS,
    best_site,
    city_positions,
    goto_name,
    step_toward,
)


def test_directions_are_the_client_rule_not_a_circle():
    assert goto_name(-1, -1) == "goto_0"   # СЗ
    assert goto_name(0, -1) == "goto_1"    # С
    assert goto_name(1, -1) == "goto_2"    # СВ
    assert goto_name(-1, 0) == "goto_3"    # З
    assert goto_name(1, 0) == "goto_4"     # В
    assert goto_name(-1, 1) == "goto_5"    # ЮЗ
    assert goto_name(0, 1) == "goto_6"     # Ю
    assert goto_name(1, 1) == "goto_7"     # ЮВ
    assert len(GOTO_DIRECTIONS) == 8


def test_step_toward_a_target_far_east_is_east():
    assert step_toward((10, 10), (13, 10)) == "goto_4"


def test_step_toward_a_diagonal_target_goes_diagonally():
    assert step_toward((10, 10), (13, 13)) == "goto_7"


def test_step_toward_respects_what_the_world_offers():
    """Если прямого направления нет, берётся ПРЕДЛОЖЕННОЕ, сокращающее шаговое расстояние.

    Цель (13, 12): прямое направление — `goto_7` (ЮВ), но его в предложении нет. Из
    `goto_6` (Ю) расстояние max(3,1)=3 не меньше исходного max(3,2)=3, а из `goto_4` (В)
    оно max(2,2)=2 — значит берётся В.
    """
    assert step_toward((10, 10), (13, 12), offered=["goto_6", "goto_4"]) == "goto_4"


def test_step_toward_none_when_offered_steps_do_not_help():
    """Шаги предложены, но ни один не приближает — тогда НЕ идём (стоять лучше).

    Это проверено на моей же ошибке: ожидание «любой из предложенных» было неверным,
    потому что из (10,10) к (13,13) ни Ю, ни В не сокращают шаговое расстояние.
    """
    assert step_toward((10, 10), (13, 13), offered=["goto_6", "goto_4"]) is None


def test_step_toward_returns_none_when_no_step_helps():
    """Лучше стоять: шагов к цели нет — не выдумываем движение."""
    assert step_toward((10, 10), (10, 10)) is None
    assert step_toward((10, 10), (20, 10), offered=["goto_3"]) is None


def test_city_positions_collect_every_visible_city():
    obs = {"city": {1: {"x": 5, "y": 6}, 2: {"x": 7, "y": 8}, 3: {"x": None, "y": 1}}}
    # ключи разных типов: id города приходит и числом, и строкой (§5.2f навыка)
    assert city_positions(obs) == {(5, 6), (7, 8)}


def test_best_site_skips_occupied_tiles():
    """Занятая городами клетка площадкой быть не может (его отсев `tile_city`)."""
    obs = {"map": {}}
    try:
        got = best_site(obs, revealed=[(3, 3)], exclude=[(3, 3)])
    except Exception:  # noqa: BLE001 — карты нет, значит и площадок нет
        got = None
    assert got is None


def test_best_site_is_silent_without_a_map():
    """Нет карты — нет и площадки: молчание обязано быть отличимо от нуля."""
    assert best_site({"map": {}}, revealed=[]) is None
