"""Правило вердикта дуэли: проверяется до того, как по нему судят о дизайне."""
from __future__ import annotations

import pytest

from metrics.duel import (
    MIRROR_MIN_GAMES,
    ab_verdict,
    mirror_verdict,
    paired_summary,
)


class TestPairedSummary:
    def test_empty_is_zero_not_a_verdict(self):
        s = paired_summary([])
        assert s['n'] == 0 and s['mean'] == 0.0

    def test_mean_and_interval_of_small_sample(self):
        s = paired_summary([1.0, -1.0])
        assert s['n'] == 2 and s['mean'] == pytest.approx(0.0)

    def test_the_interval_widens_with_spread(self):
        tight = paired_summary([1.0, 1.0, 1.0])
        wide = paired_summary([-10.0, 0.0, 10.0])
        assert (wide['ci'][1] - wide['ci'][0]) > (tight['ci'][1] - tight['ci'][0])


class TestMirrorVerdict:
    def test_too_few_games_means_no_verdict(self):
        v = mirror_verdict([5.0, 5.0])
        assert v['verdict'] == 'no_data' and v['ok'] is False
        assert str(MIRROR_MIN_GAMES) in v['reason']

    def test_a_zero_centred_difference_is_a_clean_mirror(self):
        v = mirror_verdict([2.0, -1.0, 0.5, -1.5])
        assert v['verdict'] == 'clean' and v['ok'] is True

    def test_a_systematic_difference_means_the_design_is_biased(self):
        # Одна и та же политика не может выигрывать у себя на 10 очков каждую игру.
        v = mirror_verdict([10.0, 11.0, 9.5, 10.5])
        assert v['verdict'] == 'biased' and v['ok'] is False

    def test_the_verdict_states_the_numbers_not_an_opinion(self):
        v = mirror_verdict([10.0, 11.0, 9.5, 10.5])
        assert '95% CI' in v['reason'] and 'игр 4' in v['reason']


class TestAbVerdict:
    """Сравнение вариантов X и Y: и здесь «нет различия» — результат."""

    def test_too_few_games_means_no_verdict(self):
        v = ab_verdict([2.0, 2.0])
        assert v['verdict'] == 'no_data'

    def test_no_difference_is_reported_as_absence_of_evidence(self):
        v = ab_verdict([2.0, -1.0, 0.5, -1.5])
        assert v['verdict'] == 'no_difference'
        assert 'не показано' in v['reason']

    def test_a_difference_names_the_winning_side(self):
        v = ab_verdict([5.0, 6.0, 4.5, 5.5])
        assert v['verdict'] == 'difference' and 'в пользу X' in v['reason']

    def test_the_difference_can_favour_y(self):
        v = ab_verdict([-5.0, -6.0, -4.5, -5.5])
        assert v['verdict'] == 'difference' and 'в пользу Y' in v['reason']
