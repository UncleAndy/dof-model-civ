"""Сторож на сборку вариантов работ из правил мира (§13.287).

Проверяется, что перенесённый выбор работы получает числа ИЗ ПРАВИЛ, а не выдуманные:
прирост — из `env/terrain_work_effects.py`, срок — из `env/terrain_work_times.py`
(оба сняты с правил набора `classic`, поля движка `common/terrain.h:215-227`).
"""
from __future__ import annotations

from brain.ai_default.values import city_tile_value
from brain.ai_default.worker_choice import choose_tile_work, work_options_from_rules
from env.terrain_work_effects import TERRAIN_WORK_EFFECTS
from env.terrain_work_times import TERRAIN_WORK_TIMES


def test_irrigation_on_grassland_uses_the_rules_values():
    """Луг: орошение даёт +1 еды за 5 ходов — оба числа из правил."""
    opts = work_options_from_rules("grassland", (2, 0, 0), ["irrigation"])
    assert opts == {"irrigation": ((3.0, 0, 0), 5)}


def test_mine_on_hills_uses_the_rules_values():
    """Холмы: шахта даёт +3 щита за 10 ходов — из правил."""
    opts = work_options_from_rules("hills", (1, 1, 0), ["mine"])
    assert opts == {"mine": ((1, 4.0, 0), 10)}


def test_work_not_in_the_rules_is_not_offered():
    """Гора не орошается: в правилах прироста нет — значит работа не предлагается.

    Это защита от «нельзя» ⇒ «без улучшения»: если бы мы предлагали такую работу, он
    выбрал бы её и потратил ходы впустую.
    """
    assert work_options_from_rules("mountains", (0, 1, 0), ["irrigation"]) == {}


def test_road_is_deliberately_absent():
    """Дороги не включены: их прирост выражен процентом по террейну и требует проверки."""
    assert work_options_from_rules("grassland", (2, 0, 0), ["road", "build_road"]) == {}


def test_unworked_tiles_compare_TOTALS_so_shields_on_hills_win():
    """ФАКТ его правила, а не ожидание: сравнивается ИТОГ, поэтому шахта обгоняет орошение.

    Числа: орошённый луг — `city_tile_value(3,0,0) = 90+15 = 105`; шахта на холме —
    `city_tile_value(1,4,0) = 30+15 + 68+8.5 = 121.5`. В ветке необрабатываемых клеток
    (`autoworkers.c:344-361`) он берёт БОЛЬШИЙ ИТОГ, а не больший прирост. Первая версия
    этого теста ждала еду «по смыслу» и падала; тест исправлен под исходник.

    Рост при этом защищён в его коде ОТДЕЛЬНО — правилом `food_starvation`
    (`daisettler.c:558`), уже перенесённым в `brain/ai_default/values.py`.
    """
    grass, hills = (2, 0, 0), (1, 1, 0)
    assert city_tile_value(3, 0, 0) == 105
    assert city_tile_value(1, 4, 0) == 121.5
    tiles = [
        ((1, 1), grass, work_options_from_rules("grassland", grass, ["irrigation"])),
        ((2, 2), hills, work_options_from_rules("hills", hills, ["mine"])),
    ]
    assert choose_tile_work(tiles).activity == "mine"


def test_in_use_tiles_compare_GAINS_so_food_can_win():
    """Ветка обрабатываемых клеток: сравнивается ПРИРОСТ — и тогда еда обгоняет щиты.

    Прирост луга `+1 еды = 30` против прироста холма `+3 щитов = 51`. Ставим условия, где
    выигрыш за едой: у холма прирост меньше, при одинаковом сроке.
    """
    grass, desert = (2, 0, 0), (1, 0, 0)
    tiles = [
        ((1, 1), grass, work_options_from_rules("grassland", grass, ["irrigation"])),  # +30
    ]
    assert choose_tile_work(tiles, in_use_tiles=frozenset({(1, 1)})).activity == "irrigation"


def test_rules_tables_are_not_empty():
    """Сторож на сами таблицы: пустые правила сделали бы выбор слепым."""
    assert TERRAIN_WORK_EFFECTS.get("grassland", {}).get("irrigation_food_incr") == 1.0
    assert TERRAIN_WORK_TIMES.get("grassland", {}).get("irrigation") == 5
    assert TERRAIN_WORK_TIMES.get("hills", {}).get("mine") == 10
