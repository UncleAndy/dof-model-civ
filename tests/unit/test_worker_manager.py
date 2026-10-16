"""Сторожа управляющего городом (§13.432): веса и наименьшие избытки — из его кода.

Числа взяты буквально из `server/cityturn.c:308-358` (`set_default_city_manager`), поэтому тесты
проверяют именно перенос: при размере 1 еда весит 20 против щитов 5 («рост до второго размера —
высший приоритет»), при полной житнице еда весит 0, наименьший избыток еды — 1, щитов — 1.
"""

from __future__ import annotations

from brain.ai_default.worker_manager import (
    FACTOR_FOOD_ABOVE_TRADE, FACTOR_FOOD_BELOW_TRADE, FACTOR_FOOD_SIZE1, FACTOR_SHIELD,
    choose_arrangement, factors, minimal_surplus, tile_value,
)


def test_factors_size_one_food_is_twenty():
    """Размер 1: еда 20 — «рост до второго размера высший приоритет»."""
    f = factors(1)
    assert f["food"] == FACTOR_FOOD_SIZE1 == 20.0
    assert f["shield"] == FACTOR_SHIELD == 5.0
    assert f["trade"] == 0.0
    assert f["gold"] == 2.0 and f["science"] == 2.0 and f["luxury"] == 0.0


def test_factors_by_size_and_full_granary():
    """Размер 2-3 до notradesize — еда 15; выше — 10; полная житница — еда 0."""
    assert factors(2, notradesize=4)["food"] == FACTOR_FOOD_BELOW_TRADE == 15.0
    assert factors(3, notradesize=2)["food"] == FACTOR_FOOD_ABOVE_TRADE == 10.0
    assert factors(2, granary_full=True)["food"] == 0.0
    # У него проверка полной житницы стоит ТОЛЬКО в ветви `csize > 1` (cityturn.c:320-338), поэтому
    # для размера 1 вес еды остаётся 20 независимо от житницы. Тест приведён к исходнику.
    assert factors(1, granary_full=True)["food"] == FACTOR_FOOD_SIZE1 == 20.0


def test_minimal_surplus_food_one_and_zero_when_full():
    assert minimal_surplus()["food"] == 1.0
    assert minimal_surplus()["shield"] == 1.0
    assert minimal_surplus(granary_full=True)["food"] == 0.0


def test_tile_value_trade_through_gold_and_science():
    """У него торговля весит 0, но золото и наука по 2: торговля идёт через них."""
    w = factors(1)
    assert tile_value(0, 0, 3, w) == 12.0            # 3 × (2 + 2)
    assert tile_value(2, 0, 0, w) == 40.0            # еда 20 за единицу
    assert tile_value(0, 1, 0, w) == 5.0


def test_centre_is_always_worked():
    """Центр (0, 0) входит в набор безусловно — он обрабатывается бесплатно."""
    y = {(0, 0): (1.0, 1.0, 0.0), (1, 0): (3.0, 0.0, 0.0)}
    plan = choose_arrangement(y, size=1, worked={(1, 0)}, free={}, food_cost=2.0)
    assert (0, 0) in plan["chosen"]


def test_growth_beats_shields_at_size_one():
    """Размер 1: город берёт еду 2 вместо леса с щитами 3 — еда 20 против щитов 5."""
    y = {(0, 0): (1.0, 1.0, 0.0), (1, 0): (1.0, 3.0, 0.0), (0, 1): (2.0, 0.0, 0.0)}
    plan = choose_arrangement(y, size=1, worked={(1, 0)}, free={(0, 1)}, food_cost=2.0)
    assert (0, 1) in plan["chosen"]
    assert (1, 0) not in plan["chosen"]
    assert plan["ok"] is True
    assert plan["surplus"]["food"] >= 1.0


def test_swap_improves_food_surplus():
    """Нулевой избыток при лесе: обмен на траву даёт +1 — иначе город не растёт никогда."""
    y = {(0, 0): (1.0, 1.0, 0.0), (1, 0): (1.0, 3.0, 0.0), (0, 1): (2.0, 0.0, 0.0)}
    before = choose_arrangement({k: v for k, v in y.items()},
                                size=1, worked={(1, 0)}, free={}, food_cost=2.0)
    after = choose_arrangement(y, size=1, worked={(1, 0)}, free={(0, 1)}, food_cost=2.0)
    assert before["surplus"]["food"] == 0.0
    assert after["surplus"]["food"] == 1.0
    assert before["ok"] is False and after["ok"] is True


def test_full_granary_switches_weight_to_shields():
    """Полная житница: еда не весит ничего — город берёт щиты."""
    y = {(0, 0): (1.0, 1.0, 0.0), (1, 0): (1.0, 3.0, 0.0), (0, 1): (2.0, 0.0, 0.0)}
    plan = choose_arrangement(y, size=2, worked={(1, 0)}, free={(0, 1)},
                              food_cost=2.0, granary_full=True)
    assert (1, 0) in plan["chosen"]
    assert plan["weights"]["food"] == 0.0
