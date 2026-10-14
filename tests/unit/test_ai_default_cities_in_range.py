"""Сторож: `c` у него — ЧИСЛО НАШИХ ГОРОДОВ В РАДИУСЕ, по его таблице (`daicity.c:1648-1668`).

Числа взяты из его кода, не подобраны: CITY/LOCAL = 1, PLAYER/WORLD = размер списка городов,
TILE/CADJACENT/ADJACENT = 0 («неверный радиус» для построек), CONTINENT — счёт по континентам,
которого у нас нет (и это обязано быть ВИДНО, а не превращаться в молчаливую единицу).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brain.ai_default.effects import (  # noqa: E402
    NOTES,
    cities_in_range,
    improvement_value,
)


def test_city_and_local_ranges_count_one():
    """`cities[REQ_RANGE_CITY] = cities[REQ_RANGE_LOCAL] = 1` — его строка."""
    assert cities_in_range("City", 7) == 1
    assert cities_in_range("Local", 7) == 1
    assert cities_in_range("", 7) == 1


def test_player_and_world_ranges_count_all_our_cities():
    """`cities[REQ_RANGE_PLAYER] = city_list_size(pplayer->cities)` — и WORLD/ALLIANCE/TEAM тоже."""
    assert cities_in_range("Player", 4) == 4
    assert cities_in_range("World", 4) == 4
    assert cities_in_range("player", 3) == 3          # регистр в правилах встречается разный
    assert cities_in_range("Team", 2) == 2


def test_tile_family_ranges_count_zero():
    """`cities[TILE/CADJACENT/ADJACENT] = 0` — у него это «неверный радиус» для построек."""
    assert cities_in_range("Tile", 5) == 0
    assert cities_in_range("CAdjacent", 5) == 0
    assert cities_in_range("Adjacent", 5) == 0


def test_unknown_range_is_one_but_says_so():
    """Неизвестный радиус (в том числе Continent) — единица, но с записью в замечаниях."""
    NOTES.clear()
    assert cities_in_range("Continent", 6) == 1
    assert any("Continent" in note for note in NOTES), "незнание обязано быть видно, а не молчать"
    NOTES.clear()


def _row(effect, amount, name, range_name):
    """Строка эффекта той же формы, что даёт мир: вид, величина, род, имя, РАДИУС, …"""
    return (effect, amount, "Building", name, range_name, "", "", (), ())


def test_player_range_effect_grows_with_our_city_count():
    """Один и тот же эффект радиуса «Player» ценнее при четырёх городах, чем при одном."""
    effects = [_row("Make_Happy", 2, "Temple", "Player")]
    one = improvement_value(effects, "Temple", prod={"food": 0.0, "shields": 0.0},
                            worked_tiles=0, unhappy=0.0, num_cities=1, cities=1)
    four = improvement_value(effects, "Temple", prod={"food": 0.0, "shields": 0.0},
                             worked_tiles=0, unhappy=0.0, num_cities=4, cities=4)
    assert four > one, "радиус на все города обязан считать все города, а не один"
    assert abs(four - 4.0 * one) < 1e-9, "и ровно во столько раз, сколько городов: его таблица"


def test_city_range_effect_does_not_grow_with_city_count():
    """Эффект радиуса «City» работает на ОДИН город — число городов его не увеличивает."""
    effects = [_row("Make_Happy", 2, "Temple", "City")]
    one = improvement_value(effects, "Temple", prod={"food": 0.0, "shields": 0.0},
                            worked_tiles=0, unhappy=0.0, num_cities=1, cities=1)
    four = improvement_value(effects, "Temple", prod={"food": 0.0, "shields": 0.0},
                             worked_tiles=0, unhappy=0.0, num_cities=4, cities=4)
    assert abs(four - one) < 1e-9, "город-радиус от размера царства зависеть не должен"
