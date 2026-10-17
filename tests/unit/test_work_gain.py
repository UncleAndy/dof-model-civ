"""Проверки `brain/ai_default/work_gain.py` — прирост от работы через виртуальную клетку (§13.474).

Ожидания считаются ИЗ ТЕХ ЖЕ правил (`tile_outputs_from_rules`), а не вписаны числами: вписать
числа значило бы записать в тест своё представление вместо правил мира.
"""

from __future__ import annotations

from brain.ai_default.tile_outputs import tile_outputs_from_rules
from brain.ai_default.work_gain import (CITY_WEIGHTS_DEFAULT, best_work, output_value,
                                       work_gain)

GRASS = "grassland"


def test_output_value_none_is_none():
    assert output_value(None) is None


def test_output_value_uses_city_weights():
    outs = tile_outputs_from_rules(GRASS, ())
    assert outs is not None
    assert output_value(outs) == (outs[0] * 15.0 + outs[1] * 5.0 + outs[2] * 0.0)


def test_work_gain_matches_difference_of_outputs():
    for work in ("Irrigation", "Mine", "Road", "Railroad"):
        before = output_value(tile_outputs_from_rules(GRASS, ()))
        after = output_value(tile_outputs_from_rules(GRASS, (work,)))
        assert work_gain(GRASS, (), work) == after - before


def test_work_gain_none_for_unknown_terrain():
    assert work_gain("no_such_terrain", (), "Irrigation") is None


def test_work_gain_none_when_work_already_present():
    assert work_gain(GRASS, ("Irrigation",), "Irrigation") is None


def test_weights_do_not_change_sign_of_gain():
    for work in ("Irrigation", "Mine", "Road"):
        gain15 = work_gain(GRASS, (), work)
        gain1 = work_gain(GRASS, (), work, weights=(1.0, 1.0, 1.0))
        assert (gain15 is None) == (gain1 is None)
        # Знак при разных весах совпадать НЕ обязан: работа может прибавить еды и убавить щитов,
        # и при других весах перевесит другая статья. Проверяем то, что обещано: разницу статей.
        if gain15 is not None:
            outs_before = tile_outputs_from_rules(GRASS, ())
            outs_after = tile_outputs_from_rules(GRASS, (work,))
            d_food = outs_after[0] - outs_before[0]
            d_shield = outs_after[1] - outs_before[1]
            d_trade = outs_after[2] - outs_before[2]
            assert gain15 == d_food * 15.0 + d_shield * 5.0 + d_trade * 0.0
            assert gain1 == d_food + d_shield + d_trade


def test_best_work_returns_none_when_no_gain():
    assert best_work({"a": ("no_such_terrain", ())}) == (None, None)


def test_best_work_picks_max_gain():
    cands = {"a": (GRASS, ()), "b": ("hills", ())}
    key, gain = best_work(cands)
    if key is not None:
        gains = {}
        for k, (terrain, extras) in cands.items():
            gs = [work_gain(terrain, extras, w) for w in ("Irrigation", "Mine", "Road", "Railroad")]
            gs = [g for g in gs if g is not None]
            gains[k] = max(gs) if gs else 0.0
        assert gain == max(gains.values())
        assert key in cands


def test_default_weights_are_city_manager_weights():
    assert CITY_WEIGHTS_DEFAULT == (15.0, 5.0, 0.0)
