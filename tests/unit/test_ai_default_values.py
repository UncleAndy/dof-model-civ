"""Проверка переноса чисел встроенного ИИ: сверка с его же арифметикой (§13.187)."""

from __future__ import annotations

import pytest

from brain.ai_default import values as ai
from env import config as cfg

FOOD_P = cfg.AI_FOOD_WEIGHTING          # 30
SCI_P = cfg.AI_SCIENCE_PRIORITY         # 21.6
SHIELD_P = cfg.AI_SHIELD_WEIGHTING      # 17


def tile(food, shield, trade, **kw):
    return ai.tile_sum(food, shield, trade, food_priority=FOOD_P,
                       science_priority=SCI_P, shield_priority=SHIELD_P, **kw)


class TestTileSum:
    def test_grassland_matches_the_c_source_arithmetic(self):
        # Трава: еда 2, щиты 1, торговля 0.
        # sum = (2*30 + 0*21.6 + 1*17) = 77; *= 1.5 => 115.5; еда >= 2 => *= 2 => 231.
        assert tile(2, 1, 0).sum == pytest.approx(231.0)

    def test_plain_without_growth_bonus(self):
        # Равнина: еда 1, щиты 1, торговля 0. Еда < 2, значит удвоения нет.
        # sum = (1*30 + 0 + 1*17) = 47; *= 1.5 => 70.5.
        assert tile(1, 1, 0).sum == pytest.approx(70.5)

    def test_trade_enters_with_the_science_weight_only_once(self):
        # Торговля 1 при нулевой еде: 21.6 * 1.5 = 32.4. Отдельного слагаемого науки нет.
        assert tile(0, 0, 1).sum == pytest.approx(21.6 * 1.5)

    def test_crowdedness_is_subtracted_but_never_past_one(self):
        crowded = tile(2, 1, 0, reserved=1)
        assert crowded.sum == pytest.approx(231.0 - 15.0)
        # Вычет не может съесть клетку целиком: остаётся минимум 1.
        swallowed = tile(0, 0, 0.05, reserved=9)
        assert swallowed.sum >= 1.0

    def test_city_center_is_free_of_the_crowdedness_penalty(self):
        assert tile(2, 1, 0, reserved=3, is_city_center=True).sum == pytest.approx(231.0)


class TestGates:
    def test_food_starvation_is_the_ai_threshold(self):
        # Центр 2 еды + лучшая клетка 2 еды при FOOD_COST 2: 4 > 2 — голода нет.
        assert not ai.food_starvation(tile(2, 1, 0), tile(2, 0, 0), 2.0)
        # Центр 1 + лучшая 1 = 2 <= 2 — встроенный ИИ такую площадку отвергает.
        assert ai.food_starvation(tile(1, 1, 0), tile(1, 1, 0), 2.0)

    def test_shield_starvation_is_the_ai_threshold(self):
        assert ai.shield_starvation(tile(2, 0, 1), tile(2, 0, 2))
        assert not ai.shield_starvation(tile(2, 1, 0), tile(2, 0, 0))


class TestSiteTotalAndWant:
    def test_site_total_adds_the_growth_potential(self):
        center, best = tile(2, 1, 0, is_city_center=True), tile(2, 1, 0)
        others = [tile(2, 1, 0), tile(1, 1, 0)]
        expected = center.sum + best.sum + (sum(o.sum for o in others) / 8)
        assert ai.site_total(center, best, others) == pytest.approx(expected)

    def test_amortize_matches_mort_24(self):
        assert ai.amortize(100.0, 0) == pytest.approx(100.0)
        assert ai.amortize(100.0, 24) == pytest.approx(100.0 * (1 - 1 / 24) ** 24)

    def test_want_falls_with_distance_and_pays_for_the_settler(self):
        near = ai.settler_want(1000.0, travel_turns=1, settler_shield_cost=40.0)
        far = ai.settler_want(1000.0, travel_turns=10, settler_shield_cost=40.0)
        assert near > far
        # Площадка никуда не годится: 100 очков не перекрывают поселенца в 40 щитов.
        assert ai.settler_want(100.0, travel_turns=0, settler_shield_cost=40.0) > 0
        assert ai.settler_want(30.0, travel_turns=0, settler_shield_cost=40.0) < 0