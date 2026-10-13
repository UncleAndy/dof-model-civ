"""Сторож на перенос `city_tile_value` (§13.284).

Источник: `server/advisors/infracache.c:293` закреплённого коммита freeciv.
Сторож проверяет ФОРМУЛУ, а не «похожесть»: числа взяты из исходника, и подставить
сюда свои веса нельзя, не сломав его.

Почему это важнее, чем кажется: этой ценностью встроенный ИИ выбирает, КАКУЮ работу
сделать рабочему (`autoworkers.c:530`). У нас работу выбирал счёт совпадений со списком
предпочтений, поэтому шахта и дорога шли, а еда города оставалась 2 — город стоял на
размере 1 (13.280).
"""
from __future__ import annotations

import pathlib

import pytest

from brain.ai_default.values import city_tile_value

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "drafts" / "reference" / "freeciv-src" / "server" / "advisors" / "infracache.c"


def test_empty_tile_is_zero():
    assert city_tile_value(0, 0, 0) == 0


def test_each_output_weighs_its_own_weight_plus_half_when_nonzero():
    """`value += out*W; if (out > 0) value += W/2` — строка в строку из исходника."""
    assert city_tile_value(1, 0, 0) == 30 + 15
    assert city_tile_value(0, 1, 0) == 17 + 8.5
    assert city_tile_value(0, 0, 1) == 18 + 9


def test_second_food_weighs_full_weight_only():
    """Половина веса даётся ЗА ФАКТ «статья ненулевая», а не за каждую единицу."""
    assert city_tile_value(2, 0, 0) == 60 + 15
    assert city_tile_value(3, 0, 0) == 90 + 15


def test_food_dominates_shields_which_is_the_measured_point():
    """Еда тяжелее щитов: 3 еды дороже 3 щитов — отсюда орошённый луг важнее шахты."""
    assert city_tile_value(3, 0, 0) > city_tile_value(0, 3, 0)


def test_source_line_still_says_the_same():
    """Сторож на источник: если он разошёлся с нашей копией — копия под подозрением.

    Проверяем ровно те признаки формулы, которые видно в исходнике, чтобы сторож не
    «проверял себя собой».
    """
    if not SOURCE.exists():
        pytest.skip("исходник freeciv не выложен локально (drafts/reference/freeciv-src)")
    text = SOURCE.read_text(encoding="utf-8", errors="replace")
    assert "int city_tile_value(const struct city *pcity" in text
    assert "value += food * FOOD_WEIGHTING;" in text
    assert "value += FOOD_WEIGHTING / 2;" in text
    assert "value += shield * SHIELD_WEIGHTING;" in text
    assert "value += trade * TRADE_WEIGHTING;" in text
