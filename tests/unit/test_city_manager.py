"""Числа городского управляющего — взяты из сервера, а не назначены нами.

Проверяем именно ЧИСЛА и ВЕТКИ его `set_default_city_manager` (`server/cityturn.c:313`);
если кто-то изменит коэффициент «по вкусу», эти тесты упадут и напомнят, откуда число.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brain.ai_default import city_manager as cm                            # noqa: E402


def test_food_factor_by_size():
    """Размер 1 — 20 («расти до второго жителя — высший приоритет»); иначе 10."""
    assert cm.food_factor(1, granary_is_full=False) == 20
    assert cm.food_factor(2, granary_is_full=False) == 10
    assert cm.food_factor(9, granary_is_full=False) == 10


def test_food_factor_zero_when_granary_full():
    """«We don't need more food if the granary is full» — только при размере > 1."""
    assert cm.food_factor(3, granary_is_full=True) == 0
    assert cm.food_factor(1, granary_is_full=True) == 20


def test_other_factors_are_his_numbers():
    """Щиты 5, золото 2, наука 2, торговля и роскошь — без веса, счастье — без веса."""
    assert (cm.SHIELD_FACTOR, cm.GOLD_FACTOR, cm.SCIENCE_FACTOR) == (5, 2, 2)
    assert cm.TRADE_FACTOR == 0 and cm.LUXURY_FACTOR == 0 and cm.HAPPY_FACTOR == 0


def test_score_arithmetic():
    """Сумма = пища×вес + щиты×5 + золото×2 + наука×2."""
    assert cm.score(3.0, 2.0, 1.0, 1.0, city_size=1, granary_is_full=False) == 3 * 20 + 2 * 5 + 2 + 2
    assert cm.score(0.0, 1.0, 0.0, 0.0, city_size=4, granary_is_full=False) == 5.0
    assert cm.score(2.0, 0.0, 0.0, 0.0, city_size=4, granary_is_full=True) == 0.0


def test_granary_size_from_world_numbers():
    """`city_granary_size` на числах classic: 20 на первом жителе, +10 на каждого следующего."""
    assert cm.granary_size(0) == 0
    assert cm.granary_size(1) == 20
    assert cm.granary_size(2) == 30
    assert cm.granary_size(3) == 40


def test_granary_full_unknown_stock_is_not_full():
    """Незнание склада еды НЕ означает «житница полна»: иначе вес пищи падал бы до нуля."""
    assert cm.granary_full(2, None) is False
    assert cm.granary_full(2, 30) is True
    assert cm.granary_full(2, 29) is False


def test_minimums_are_his():
    """Пища ≥ 1 и щиты ≥ 1; при полной житнице пища ≥ 0."""
    assert cm.minimums_ok(1.0, 1.0, False) is True
    assert cm.minimums_ok(0.0, 1.0, False) is False
    assert cm.minimums_ok(0.0, 1.0, True) is True
    assert cm.minimums_ok(1.0, 0.0, False) is False


def test_minimums_with_unknown_values_do_not_forbid():
    """Незнание приростов — не запрет: запрет только на ИЗМЕРЕННОМ нарушении."""
    assert cm.minimums_ok(None, None, False) is True
    assert cm.minimums_ok(None, 1.0, False) is True