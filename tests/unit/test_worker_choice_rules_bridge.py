"""Сторож на сборку вариантов работ из правил мира (§13.287, поправка §13.291).

Проверяется, что перенесённый выбор работы получает числа ИЗ ПРАВИЛ, а не выдуманные:
прирост — из `env/terrain_work_effects.py`, срок — из `env/terrain_work_times.py`
(оба сняты с правил набора `classic`, поля движка `common/terrain.h:215-227`).
"""
from __future__ import annotations

from brain.ai_default.tile_outputs import tile_outputs_from_rules
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
    opts = work_options_from_rules("hills", (1, 0, 0), ["mine"])
    assert opts == {"mine": ((1, 3.0, 0), 10)}


def test_work_not_in_the_rules_is_not_offered():
    """Гора не орошается: в правилах прироста нет — значит работа не предлагается.

    Это защита от «нельзя» ⇒ «без улучшения»: если бы мы предлагали такую работу, он
    выбрал бы её и потратил ходы впустую.
    """
    assert work_options_from_rules("mountains", (0, 1, 0), ["irrigation"]) == {}


def test_roads_were_absent_until_the_percent_linkage_was_verified():
    """Дороги были исключены СОЗНАТЕЛЬНО, пока связка процента не проверена.

    Прежний сторож требовал пустоты. Теперь связка подтверждена самими правилами
    (`terrain.ruleset:119`), и требование снято — но не отменено молча: этот тест стережёт,
    что дорога предлагается, а холмы с нулевым процентом — нет.
    """
    assert work_options_from_rules("grassland", (2, 0, 0), ["build_road"])
    assert work_options_from_rules("hills", (1, 0, 0), ["build_road"]) == {}


def test_unworked_tiles_compare_TOTALS_not_gains():
    """Ветка необрабатываемых клеток: сравнивается ИТОГ, а не прирост (`autoworkers.c:344-361`).

    Орошённый луг `105` против шахты холма `104.5` — при том, что ПРИРОСТ у шахты больше
    (`104.5 − 45 = 59.5` против `105 − 75 = 30`). Побеждает всё равно луг: решает итог.
    Если бы правило сравнивало приросты, победила бы шахта. Тест стережёт именно это.
    """
    grass, hills = tile_outputs_from_rules("grassland", ()), tile_outputs_from_rules("hills", ())
    assert city_tile_value(*hills) == 45.0
    assert (city_tile_value(1, 3, 0) - city_tile_value(*hills)) > (
        city_tile_value(3, 0, 0) - city_tile_value(*grass))
    tiles = [
        ((1, 1), grass, work_options_from_rules("grassland", grass, ["irrigation"])),
        ((2, 2), hills, work_options_from_rules("hills", hills, ["mine"])),
    ]
    choice = choose_tile_work(tiles)
    assert choice.activity == "irrigation", choice


def test_in_use_tiles_compare_GAINS():
    """Ветка обрабатываемых клеток сравнивает прирост — и тогда выбирается больший."""
    grass, hills = tile_outputs_from_rules("grassland", ()), tile_outputs_from_rules("hills", ())
    tiles = [
        ((1, 1), grass, work_options_from_rules("grassland", grass, ["irrigation"])),  # +30
        ((2, 2), hills, work_options_from_rules("hills", hills, ["mine"])),            # +59.5
    ]
    choice = choose_tile_work(tiles, in_use_tiles=frozenset({(1, 1), (2, 2)}))
    assert choice.activity == "mine", choice


def test_rules_tables_are_not_empty():
    """Сторож на сами таблицы: пустые правила сделали бы выбор слепым."""
    assert TERRAIN_WORK_EFFECTS.get("grassland", {}).get("irrigation_food_incr") == 1.0
    assert TERRAIN_WORK_TIMES.get("grassland", {}).get("irrigation") == 5
    assert TERRAIN_WORK_TIMES.get("hills", {}).get("mine") == 10


def test_road_on_grassland_is_offered_with_the_rules_percent():
    """Дорога: прирост = `road.trade_incr` × `road_trade_incr_pct` террейна.

    Связка — из самих правил: `road_trade_incr_pct = percent of road trade_incr applied to
    this terrain` (terrain.ruleset:119). Луг: 100 % от 1 → `+1 торговли` за 2 хода.
    """
    assert work_options_from_rules("grassland", (2, 0, 0), ["build_road"]) == {
        "build_road": ((2, 0, 1.0), 2)}


def test_road_on_hills_is_not_offered_because_the_rules_say_zero_percent():
    """Холмы: `road_trade_incr_pct = 0` → дорога не предлагается (не тратим ходы впустую)."""
    assert work_options_from_rules("hills", (1, 0, 0), ["build_road"]) == {}


def test_trade_is_worth_more_than_shields_in_his_weights():
    """Факт его весов: `+1 торговли (18)` чуть дороже `+1 щита (17)` — поэтому дорогу включать
    было нельзя без проверки связки, а теперь можно."""
    assert city_tile_value(2, 0, 1) - city_tile_value(2, 0, 0) == 27.0   # 18 + половина 9*2
    assert city_tile_value(2, 1, 0) - city_tile_value(2, 0, 0) == 25.5   # 17 + половина 8.5*2
