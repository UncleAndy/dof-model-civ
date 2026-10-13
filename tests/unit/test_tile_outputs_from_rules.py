"""Сторож на сборку выходов клетки из правил мира (§13.291)."""

from __future__ import annotations

from brain.ai_default.tile_outputs import tile_outputs_from_rules
from brain.ai_default.values import city_tile_value


def test_plain_grassland_is_the_rules_base():
    assert tile_outputs_from_rules("grassland", ()) == (2.0, 0.0, 0.0)


def test_irrigated_grassland_adds_the_rules_increment():
    """Орошение луга: +1 еды (правила: `irrigation_food_incr = 1`)."""
    assert tile_outputs_from_rules("grassland", ("Irrigation",)) == (3.0, 0.0, 0.0)


def test_hills_base_is_one_food_and_no_shields():
    """Основа холмов по правилам — `(1, 0, 0)`.

    Это важно для выбора: раньше в тестах я подставлял холмам `(1, 1, 0)` по привычке, и
    из-за этого шахта холма выглядела выгоднее, чем она есть (13.291).
    """
    assert tile_outputs_from_rules("hills", ()) == (1.0, 0.0, 0.0)


def test_mined_hills_adds_three_shields():
    """Шахта на холмах: +3 щита (правила: `mining_shield_incr = 3`)."""
    assert tile_outputs_from_rules("hills", ("Mine",)) == (1.0, 3.0, 0.0)


def test_road_on_grassland_gives_one_trade_from_the_terrain_share():
    """Дорога на лугу: `road_trade_incr = 1` при `road_trade_incr_pct = 100` → +1 торговли."""
    assert tile_outputs_from_rules("grassland", ("Road",)) == (2.0, 0.0, 1.0)


def test_road_on_hills_gives_nothing_because_the_rules_say_zero():
    """У холмов `road_trade_incr_pct` в правилах не задан → дорога торговли не даёт."""
    assert tile_outputs_from_rules("hills", ("Road",)) == (1.0, 0.0, 0.0)


def test_unknown_extra_adds_nothing_and_unknown_terrain_is_None():
    """Незнакомое не даёт прироста, незнакомый террейн — None, а не нули.

    Подставлять ноль нельзя: «неизвестно» не должно выглядеть как «клетка без выходов».
    """
    assert tile_outputs_from_rules("grassland", ("SomethingNew",)) == (2.0, 0.0, 0.0)
    assert tile_outputs_from_rules("nowhere", ()) is None


def test_values_feed_the_ported_city_tile_value():
    """Ценности по его числу (`infracache.c:293`) на клетках ИЗ ПРАВИЛ.

    Числа посчитаны его формулой (`знание в `brain/ai_default/values.py`), а не подобраны:
    `city_tile_value(2,0,0) = 60+15 = 75`, `(2,0,1) = 75 + 18+9 = 102`,
    `(3,0,0) = 90+15 = 105`.
    """
    bare = city_tile_value(*tile_outputs_from_rules("grassland", ()))
    road = city_tile_value(*tile_outputs_from_rules("grassland", ("Road",)))
    irr = city_tile_value(*tile_outputs_from_rules("grassland", ("Irrigation",)))
    assert (bare, road, irr) == (75.0, 102.0, 105.0)
    assert bare < road < irr


def test_irrigated_grassland_beats_mined_hills_by_one_half_point():
    """Факт его весов на клетках из правил: `105` против `104.5` — еда обгоняет щиты.

    Орошённый луг `(3,0,0) = 90+15 = 105`; шахта холма `(1,3,0) = 30+15 + 51+8.5 = 104.5`.
    Разрыв в половину очка — и он в пользу ЕДЫ, то есть в пользу роста.
    """
    grass_irr = city_tile_value(*tile_outputs_from_rules("grassland", ("Irrigation",)))
    hill_mined = city_tile_value(*tile_outputs_from_rules("hills", ("Mine",)))
    assert grass_irr == 105.0 and hill_mined == 104.5
    assert grass_irr > hill_mined
