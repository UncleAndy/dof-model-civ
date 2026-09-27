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
from baselines.run_duel import _dead_side, _freeze_evidence, _frozen


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


class TestFreezeEvidence:
    """Различать «правило замерзло» и «отказ инструмента» можно только по улике.

    Ноль решений бывает двух природ: сторона не получила державу (брак, игру
    повторять) или сторона получала предложения и отказалась действовать
    (исход правила «строго > 0», игру выбрасывать нельзя — иначе выборка смещена).
    """

    def test_a_veto_line_is_evidence(self):
        assert _freeze_evidence("  [вето ядра 1] кандидатов 6, net_delta=+0.000")

    def test_an_empty_offer_line_is_evidence(self):
        assert _freeze_evidence("[выбор-пуст 1] ход 2: предложено действий 9")

    def test_no_candidates_line_is_evidence(self):
        assert _freeze_evidence("[нет-кандидатов 1] сущностей=93")

    def test_silence_is_not_evidence(self):
        # Молчание = «не знаем»: сторона остаётся подозреваемой в отказе инструмента.
        assert not _freeze_evidence("Reset with port: 6300\n [turn 10/30 ...]")

    def test_empty_text_is_not_evidence(self):
        assert not _freeze_evidence("")
        assert not _freeze_evidence(None)


class TestFrozenGame:
    """Замерзшая игра остаётся в выборке, сломанная — нет."""

    def _game(self, tmp_path, decisions, text):
        log = tmp_path / "duel_1_a.log"
        log.write_text(text)
        return {"a": {"turns": 30, "decisions_per_turn_mean": decisions},
                "log_a": str(log)}

    def test_a_dead_side_with_evidence_is_frozen(self, tmp_path):
        g = self._game(tmp_path, 0.0, "[вето ядра 1] кандидатов 6, net_delta=+0.000\n")
        assert _frozen(g, "a") is True

    def test_a_dead_side_without_evidence_is_not_frozen(self, tmp_path):
        g = self._game(tmp_path, 0.0, "Reset with port: 6300\n")
        assert _frozen(g, "a") is False

    def test_an_active_side_is_never_frozen(self, tmp_path):
        g = self._game(tmp_path, 0.5, "[вето ядра 1]\n")
        assert _frozen(g, "a") is False

    def test_a_missing_log_is_not_frozen(self):
        g = {"a": {"turns": 30, "decisions_per_turn_mean": 0.0},
             "log_a": "/нет/такого/файла.log"}
        assert _frozen(g, "a") is False
