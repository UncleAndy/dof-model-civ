"""Значения шкал желаний должны совпадать с C-источником — иначе «перенос» снова окажется своим."""

from brain.ai_default import want_scales as ws


def test_constants_match_source():
    assert ws.DAI_WANT_BELOW_MIL_EMERGENCY == 1000.0
    assert ws.DAI_WANT_DOMESTIC_MAX == 750.075
    assert ws.RESULT_IS_ENOUGH == 250
    assert ws.GROWTH_POTENTIAL_DEEMPHASIS == 8
    assert ws.PERFECTION == 3
    assert ws.MORT == 24
    assert ws.WORKER_FACTOR == 1024
    assert ws.AI_CITY_RECALC_SPEED == 5


def test_domestic_cap_is_below_emergency():
    """Потолок внутренних желаний обязан быть ниже порога военной тревоги."""
    assert ws.DAI_WANT_DOMESTIC_MAX < ws.DAI_WANT_BELOW_MIL_EMERGENCY


def test_caps_and_enough():
    assert ws.domestic_capped(5000.0) == ws.DAI_WANT_DOMESTIC_MAX
    assert ws.domestic_capped(10.0) == 10.0
    assert ws.below_mil_emergency(5000.0) == ws.DAI_WANT_BELOW_MIL_EMERGENCY
    assert ws.enough(ws.RESULT_IS_ENOUGH) is True
    assert ws.enough(ws.RESULT_IS_ENOUGH - 1) is False


def test_recalc_period_range():
    """`rand(speed) + speed` даёт 5..9 — как у него."""
    assert ws.recalc_period(0) == 5
    assert ws.recalc_period(4) == 9
