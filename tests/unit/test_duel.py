"""Правило вердикта дуэли: проверяется до того, как по нему судят о дизайне."""
from __future__ import annotations

import pytest

from metrics.duel import (
    MIRROR_MIN_GAMES,
    ab_verdict,
    cumulative,
    mirror_verdict,
    paired_summary,
)
from baselines.run_duel import _dead_side


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


class TestCumulative:
    """Траектория счёта: прирост есть только там, где счёт менялся."""

    SERIES = [{"turn": 3, "delta": 2.0}, {"turn": 7, "delta": 3.0},
              {"turn": 12, "delta": -1.0}]

    def test_the_whole_trajectory_sums_up(self):
        assert cumulative(self.SERIES) == pytest.approx(4.0)

    def test_a_horizon_keeps_only_what_happened_by_then(self):
        assert cumulative(self.SERIES, upto=3) == pytest.approx(2.0)
        assert cumulative(self.SERIES, upto=7) == pytest.approx(5.0)
        assert cumulative(self.SERIES, upto=6) == pytest.approx(2.0)

    def test_an_empty_series_is_zero_not_an_error(self):
        assert cumulative([]) == 0.0

    def test_a_falling_score_is_kept(self):
        # Город потерян — счёт падает; выбрасывать такие события значит подгонять.
        assert cumulative([{"turn": 1, "delta": 5.0},
                           {"turn": 2, "delta": -4.0}]) == pytest.approx(1.0)

    def test_broken_entries_do_not_crash_the_analysis(self):
        assert cumulative([{"turn": "нет"}, None, {"delta": 1.0}]) == pytest.approx(1.0)


class TestDeadSide:
    """«Пассивная политика» и «отказ инструмента» — разные вещи.

    Пассивная политика (любопытство ВЫКЛ) делает редкие, но настоящие выборы —
    на живых данных 0.04–0.05 решения/ход. Ровно 0.00 при полном числе ходов и
    rc=0 значит, что ход стороне не достался: державу не взяли.
    """

    def test_a_side_that_never_acted_is_dead(self):
        assert _dead_side({"turns": 50, "decisions_per_turn_mean": 0.0}) is True

    def test_a_merely_passive_side_is_alive(self):
        assert _dead_side({"turns": 50, "decisions_per_turn_mean": 0.04}) is False

    def test_an_erroring_side_is_not_reported_as_dead(self):
        # У неё своя причина выпадения; смешивать диагнозы нельзя.
        assert _dead_side({"error": "таймаут", "decisions_per_turn_mean": 0.0}) is False

    def test_an_absent_record_is_not_called_dead(self):
        assert _dead_side(None) is False

    def test_missing_field_counts_as_never_acted(self):
        assert _dead_side({"turns": 50}) is True
