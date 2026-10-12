"""Правило защиты — встроенного ИИ: опасность считают, а не «видимость» (§13.190).

Прежнее наше правило ставило войско в очередь при одном факте: виден чужой юнит или у
города нет защитника. На стенде это дало 2.2 военных юнита против 0.1 у встроенного ИИ.
Его правило (`daimilitary.c`): юнит опасен, только если он способен напасть и может дойти.
"""

from __future__ import annotations

import pytest

from brain.ai_default import military as mil


class TestAttackRating:
    def test_matches_the_source_formula(self):
        # advgoto.c:381 — attack * hp * firepower / POWER_DIVIDER, делитель = 10 * 3.
        assert mil.POWER_DIVIDER == 30
        assert mil.attack_rating(1.0, 10.0, 1.0) == pytest.approx(10.0 / 30.0)

    def test_a_unit_without_attack_is_not_dangerous(self):
        assert mil.attack_rating(0.0, 10.0, 1.0) == 0.0


class TestDanger:
    def test_scout_without_attack_is_not_a_threat(self):
        scout = mil.Threat(attack_strength=0.0, hp=10.0, move_rate=3.0, distance=2)
        assert mil.city_danger([scout]) == 0.0

    def test_far_unit_is_not_a_threat_within_the_horizon(self):
        far = mil.Threat(attack_strength=4.0, hp=10.0, move_rate=1.0, distance=40)
        assert far.turns_to_reach() > 10.0
        assert mil.city_danger([far]) == 0.0

    def test_reachable_attacker_is_a_threat(self):
        near = mil.Threat(attack_strength=4.0, hp=10.0, move_rate=2.0, distance=4)
        assert near.turns_to_reach() == pytest.approx(2.0)
        assert mil.city_danger([near]) == pytest.approx(near.rating)

    def test_own_units_are_not_threats(self):
        own = mil.Threat(attack_strength=4.0, hp=10.0, move_rate=2.0, distance=1,
                         is_foreign=False)
        assert mil.city_danger([own]) == 0.0


class TestDefenderNeed:
    def test_no_danger_means_no_defender_even_without_a_garrison(self):
        # Это и есть отличие от нашего прежнего правила: видимость чужого юнита
        # больше не повод строить войско.
        assert mil.needs_defender(0.0, defenders=0) is False

    def test_danger_without_a_garrison_asks_for_a_defender(self):
        assert mil.needs_defender(3.0, defenders=0) is True

    def test_existing_garrison_covers_the_need(self):
        assert mil.needs_defender(3.0, defenders=1) is False

    def test_wanted_count_covers_the_danger(self):
        assert mil.defenders_wanted(0.0) == 0
        assert mil.defenders_wanted(25.0, defence_rating=10.0) == 3
        assert mil.defenders_wanted(5.0, defence_rating=10.0) == 1
        assert mil.defenders_wanted(5.0) == 1        # сила защитника неизвестна — минимум один