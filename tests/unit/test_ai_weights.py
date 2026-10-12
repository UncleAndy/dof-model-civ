"""Веса города — ЧИСЛА ВСТРОЕННОГО ИИ, а не наши (§13.186).

Сторож нужен потому, что эти числа не выдуманы и не подобраны: они взяты из кода
встроенного ИИ-игрока. Источник — `server/advisors/advbuilding.h:19-21`
(FOOD_WEIGHTING 30, SHIELD_WEIGHTING 17, TRADE_WEIGHTING 18) и
`server/advisors/advdata.c:499-508` (при желании науки science_priority = 18*1.2 = 21.6,
gold_priority = 18). Если кто-то поменяет отношения между выходами, он порвёт связь с
источником — тест это заметит.
"""

from __future__ import annotations

import pytest

from env import config as cfg


class TestAiWeights:
    def test_weights_match_the_builtin_ai_source(self):
        assert cfg.AI_FOOD_WEIGHTING == 30.0
        assert cfg.AI_SHIELD_WEIGHTING == 17.0
        assert cfg.AI_TRADE_WEIGHTING == 18.0
        assert cfg.AI_SCIENCE_PRIORITY == pytest.approx(21.6)
        assert cfg.AI_GOLD_PRIORITY == pytest.approx(18.0)
        assert cfg.AI_LUXURY_PRIORITY == pytest.approx(1.0)

    def test_city_options_keep_the_ai_proportions(self):
        ratio = cfg.AI_SHIELD_WEIGHTING / cfg.CITY_M2_SHIELD
        assert cfg.CITY_M2_FOOD == pytest.approx(cfg.AI_FOOD_WEIGHTING / ratio)
        assert cfg.CITY_M2_TRADE == pytest.approx(cfg.AI_SCIENCE_PRIORITY / ratio)
        assert cfg.CITY_M2_GOLD == pytest.approx(cfg.AI_GOLD_PRIORITY / ratio)
        assert cfg.CITY_M2_LUXURY == pytest.approx(cfg.AI_LUXURY_PRIORITY / ratio)

    def test_food_outweighs_shields_as_it_does_for_the_ai(self):
        # У встроенного ИИ еда тяжелее щитов (30 против 17): без этого город не растёт,
        # потому что рост ему мере невидим. Это и было измеренное расхождение.
        assert cfg.CITY_M2_FOOD > cfg.CITY_M2_SHIELD
        assert cfg.CITY_M2_TRADE > cfg.CITY_M2_SHIELD   # торговля идёт весом науки 21.6