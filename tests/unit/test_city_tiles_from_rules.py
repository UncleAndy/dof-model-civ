"""Сторож на оценку клетки города перенесённым числом (§13.292)."""

from __future__ import annotations

from brain.ai_default.city_tiles import (
    parse_city_tile_action,
    tile_value_from_rules,
    unwork_gain,
    work_gain,
)


def test_parse_follows_the_client_format():
    """Формат имён задан клиентом: `city_actions.py:127` → индекс, dx, dy."""
    assert parse_city_tile_action("city_unwork_9_-2_0") == (9, -2, 0)
    assert parse_city_tile_action("city_work_3_1_-1") == (3, 1, -1)
    assert parse_city_tile_action("city_unwork_None_1_0") is None
    assert parse_city_tile_action("unit/mine") is None


def test_tile_value_uses_the_ported_number_and_the_rules():
    """Луг `(2,0,0) → 75`, орошённый луг `(3,0,0) → 105`, дорога `(2,0,1) → 102`."""
    assert tile_value_from_rules("Grassland", ()) == 75.0
    assert tile_value_from_rules("Grassland", ("Irrigation",)) == 105.0
    assert tile_value_from_rules("Grassland", ("Road",)) == 102.0


def test_unknown_terrain_is_None_not_zero():
    """Неизвестный террейн — None, а не ноль: «неизвестно» не равно «клетка без выходов»."""
    assert tile_value_from_rules("Nowhere", ()) is None


def test_unwork_pays_only_to_free_a_citizen_for_a_better_tile():
    """Урок 13.290: снятие окупается только свободной клеткой ЛУЧШЕ снимаемой.

    Холм `45` против свободного луга `75` — снимать стоит (выигрыш 30). Обратный случай
    (снимаем луг `75`, свободен только холм `45`) выигрыша не даёт: 0, ход не тратится.
    """
    assert unwork_gain(45.0, [75.0]) == 30.0
    assert unwork_gain(75.0, [45.0]) == 0.0
    assert unwork_gain(45.0, []) == 0.0
    assert unwork_gain(None, [75.0]) == 0.0


def test_work_gain_prefers_the_better_tile_and_hides_negatives():
    assert work_gain(105.0, 75.0) == 30.0
    assert work_gain(45.0, 75.0) == 0.0
    assert work_gain(75.0, None) == 75.0
    assert work_gain(None, 75.0) == 0.0


def test_unworked_hill_beats_free_grassland_only_after_the_citizen_is_freed():
    """Полный смысл пары: холм занят, луг свободен — снять и занять даёт рост еды.

    Холм `45` → луг `75`: снятие даёт 30, постановка на луг даёт 75 при пустой лучшей. Вместе
    это и есть «снять плохую → занять лучшую», порядок взят у него, а не придуман.
    """
    hill = tile_value_from_rules("Hills", ())
    grass = tile_value_from_rules("Grassland", ())
    assert (hill, grass) == (45.0, 75.0)
    assert unwork_gain(hill, [grass]) > 0
    assert work_gain(grass, None) == 75.0
