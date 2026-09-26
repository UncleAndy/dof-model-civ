"""Счёт игры как метрика исхода: арифметика и ловушка стартового значения.

Счёт — единственный сигнал исхода, который считает сервер, а не наш разбор
наблюдения. Поэтому с ним связаны две вещи, которые легко испортить: мир отдаёт
счёт **приростом**, и первый прирост на самом деле не прирост, а весь накопленный
счёт сразу (у контроллера `_last_score` стартует с нуля). Перепутать — значит
завысить «выигрыш» на всю начальную оценку.
"""
from __future__ import annotations

import pytest

from metrics.tracker import MatchMetrics


class TestScoreArithmetic:
    def test_first_value_is_the_starting_score_not_a_gain(self):
        m = MatchMetrics()
        m.record_score(1, 7.0)      # это стартовый счёт, а не прирост
        m.record_score(2, 3.0)      # а это прирост
        m.record_score(3, 0.0)
        assert m.score_first == 7.0
        assert m.score_cum == 10.0
        assert m.score_gain == pytest.approx(3.0)

    def test_events_count_only_non_zero_deltas(self):
        m = MatchMetrics()
        for delta in (5.0, 0.0, 0.0, 2.0):
            m.record_score(1, delta)
        assert m.score_events == 2
        assert m.score_max_step == 5.0

    def test_zero_score_never_claims_a_gain(self):
        m = MatchMetrics()
        m.record_score(1, 0.0)
        assert m.score_gain == 0.0 and m.score_events == 0

    def test_before_any_recording_there_is_no_gain_claim(self):
        # Отсутствие данных — не «ноль очков»: до первого вызова мы не знаем
        # ничего, и выигрыш обязан быть 0.0 только как «неизвестно».
        m = MatchMetrics()
        assert m.score_gain == 0.0 and m.score_first is None

    def test_a_falling_score_is_recorded_as_such(self):
        # Счёт может и падать (город потерян) — отрицательный прирост это факт,
        # а не повод его отбросить.
        m = MatchMetrics()
        m.record_score(1, 10.0)
        m.record_score(2, -4.0)
        assert m.score_gain == pytest.approx(-4.0)
        assert m.score_max_step == 10.0

    def test_the_series_keeps_turns_and_deltas(self):
        m = MatchMetrics()
        m.record_score(1, 1.0)
        m.record_score(7, 2.0)
        assert m.score_series == [{"turn": 1, "delta": 1.0},
                                  {"turn": 7, "delta": 2.0}]

    def test_the_series_is_capped_and_does_not_grow_beyond_the_record(self):
        m = MatchMetrics()
        for i in range(500):
            m.record_score(i, 1.0)
        assert len(m.score_series) <= 400

    def test_it_lands_in_the_serialised_record(self):
        m = MatchMetrics(agent_name="dof_expansionist")
        m.record_score(1, 4.0)
        m.record_score(2, 6.0)
        payload = m.to_dict()
        assert payload["score_gain"] == pytest.approx(6.0)
        assert payload["score_cum"] == pytest.approx(10.0)
        assert payload["score_events"] == 2
