"""
Unit tests for the unified metrics recorder and the statistics helpers.

These cover the measurement gaps that made the earlier comparison meaningless:
an irreversibility ratio that ignored skipped turns, and no confidence intervals.
"""
import pytest

from metrics.tracker import MatchMetrics, StepRecord, agent_turns
from metrics.stats import (
    bootstrap_diff_ci,
    ci95,
    cohens_d,
    mean,
    sem,
    stdev,
    t_critical_95,
)


# ═══════════════════════════════════════════════════════════════════════════════
# MatchMetrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestMatchMetrics:
    def test_records_reversible_action(self):
        m = MatchMetrics(agent_name="dof_defensive")
        rec = m.record_step(turn=1, dof_index=0.5, entity_count=10,
                            action=("unit", 102, "fortify"))
        assert rec.is_reversible is True
        assert rec.skipped is False
        assert m.actions_issued == 1
        assert m.irreversible_actions == 0
        assert m.irreversibility_ratio == 0.0

    def test_records_irreversible_action(self):
        m = MatchMetrics()
        m.record_step(1, 0.5, 10, ("unit", 102, "disband"))
        assert m.irreversible_actions == 1
        assert m.actions_issued == 1
        assert m.irreversibility_ratio == 1.0

    def test_none_action_is_a_skipped_turn_not_a_safe_action(self):
        """A no-op turn must not inflate 'reversible actions' — this was the
        bug that made the random baseline look perfect."""
        m = MatchMetrics()
        rec = m.record_step(1, 0.5, 10, None)
        assert rec.skipped is True
        assert rec.is_reversible is None
        assert m.skipped_turns == 1
        assert m.actions_issued == 0
        assert m.irreversibility_ratio == 0.0  # no denominator -> undefined, 0

    def test_mixed_turns_ratio_uses_issued_only(self):
        m = MatchMetrics()
        m.record_step(1, 0.5, 10, ("unit", 1, "fortify"))    # reversible
        m.record_step(2, 0.5, 10, None)                       # skipped
        m.record_step(3, 0.5, 10, ("unit", 1, "disband"))     # irreversible
        m.record_step(4, 0.5, 10, ("unit", 1, "goto_3"))      # reversible
        assert m.turns_played == 4
        assert m.actions_issued == 3
        assert m.skipped_turns == 1
        assert m.irreversible_actions == 1
        assert m.irreversibility_ratio == pytest.approx(1 / 3)

    def test_dof_and_entity_aggregates(self):
        m = MatchMetrics()
        m.record_step(1, 0.2, 90, None)
        m.record_step(2, 0.4, 95, None)
        m.record_step(3, 0.3, 92, None)
        assert m.avg_dof == pytest.approx(0.3)
        assert m.final_dof == pytest.approx(0.3)
        assert m.min_ent == 90
        assert m.max_ent == 95

    def test_empty_metrics_are_zeroed(self):
        m = MatchMetrics()
        assert m.turns_played == 0
        assert m.avg_dof == 0.0
        assert m.final_dof == 0.0
        assert m.irreversibility_ratio == 0.0

    def test_to_dict_keys(self):
        m = MatchMetrics(agent_name="random")
        m.record_step(1, 0.5, 10, ("unit", 1, "attack_2"))
        d = m.to_dict()
        assert d["agent"] == "random"
        assert d["turns"] == 1
        assert d["irreversible_actions"] == 1
        assert d["irreversibility_ratio"] == 1.0
        assert "skipped_turns" in d and "actions_issued" in d

    def test_series_are_opt_in(self):
        m = MatchMetrics()
        m.record_step(1, 0.5, 10, ("unit", 1, "fortify"))
        m.record_step(2, 0.6, 11, None)
        assert "dof_series" not in m.to_dict()

        m.include_series = True
        payload = m.to_dict()
        # per-turn series
        assert payload["dof_series"] == [0.5, 0.6]
        assert payload["entity_series"] == [10, 11]
        assert payload["turns_series"] == [1, 2]
        assert payload["decisions_per_turn"] == [1, 0]
        # per-decision series
        assert payload["decisions"] == [["unit", 1, "fortify"]]
        assert payload["decision_turns"] == [1]
        assert payload["reversible_series"] == [True]

    def test_decisions_are_counted_separately_from_turns(self):
        """A turn may contain several decisions; a no-op turn contains none."""
        m = MatchMetrics()
        m.record_step(1, 0.5, 10, None)              # turn 1: no decision
        m.record_step(2, 0.6, 10, None)
        m.record_decision(2, ("unit", 1, "goto_0"))
        m.record_decision(2, ("unit", 2, "fortify"))
        m.record_decision(2, ("unit", 3, "disband"))
        m.record_step(3, 0.7, 10, None)

        assert m.turns_played == 3
        assert m.actions_issued == 3
        assert m.irreversible_actions == 1
        assert m.irreversibility_ratio == pytest.approx(1 / 3)
        assert m.decisions_per_turn == [0, 3, 0]
        # skipped_turns counts turns with no decision at all
        assert m.skipped_turns == 2


class TestAgentTurns:
    def test_aggregates_records(self):
        records = [
            {"avg_dof": 0.2, "irreversibility_ratio": 0.0, "turns": 10, "error": ""},
            {"avg_dof": 0.4, "irreversibility_ratio": 1.0, "turns": 20, "error": "x"},
        ]
        summary = agent_turns(records)
        assert summary["n"] == 2
        assert summary["avg_dof"] == pytest.approx(0.3)
        assert summary["irreversibility_ratio"] == pytest.approx(0.5)
        assert summary["turns"] == pytest.approx(15)
        assert summary["errors"] == 1

    def test_empty(self):
        assert agent_turns([]) == {"n": 0}


# ═══════════════════════════════════════════════════════════════════════════════
# Statistics
# ═══════════════════════════════════════════════════════════════════════════════

class TestStats:
    def test_mean_and_stdev(self):
        values = [1.0, 2.0, 3.0, 4.0]
        assert mean(values) == pytest.approx(2.5)
        assert stdev(values) == pytest.approx(1.2909944, rel=1e-6)

    def test_stdev_needs_two_points(self):
        assert stdev([5.0]) == 0.0
        assert stdev([]) == 0.0

    def test_sem(self):
        assert sem([1.0, 2.0, 3.0, 4.0]) == pytest.approx(0.6454972, rel=1e-6)

    def test_ci95_known_sample(self):
        # t(3, 0.975)=3.18245 ; sem=0.6455 -> half width ~2.0544
        lo, hi = ci95([1.0, 2.0, 3.0, 4.0])
        assert lo == pytest.approx(0.4456, abs=1e-3)
        assert hi == pytest.approx(4.5544, abs=1e-3)

    def test_ci95_wide_for_single_point(self):
        assert ci95([0.7]) == (0.7, 0.7)

    def test_ci95_empty(self):
        assert ci95([]) == (0.0, 0.0)

    def test_ci95_narrows_with_n(self):
        tight = ci95([0.5] * 100 + [0.6])
        wide = ci95([0.5, 0.6])
        assert (tight[1] - tight[0]) < (wide[1] - wide[0])

    def test_t_critical_monotone_and_conservative(self):
        assert t_critical_95(1) > t_critical_95(10) > t_critical_95(120)
        assert t_critical_95(500) == pytest.approx(1.96)
        assert t_critical_95(0) == float("inf")
        # df not tabulated -> rounded down (more conservative, larger t)
        assert t_critical_95(33) == t_critical_95(30)

    def test_bootstrap_diff_detects_clear_difference(self):
        a = [0.30, 0.32, 0.31, 0.33, 0.29, 0.30]
        b = [0.10, 0.11, 0.09, 0.12, 0.10, 0.11]
        lo, hi, point = bootstrap_diff_ci(a, b, n_resamples=2000, seed=1)
        assert point > 0
        assert lo > 0, "a strictly larger than b should exclude 0"

    def test_bootstrap_diff_identical_samples_include_zero(self):
        a = [0.2, 0.3, 0.25, 0.22, 0.28]
        lo, hi, point = bootstrap_diff_ci(a, list(a), n_resamples=2000, seed=1)
        assert point == pytest.approx(0.0)
        assert lo < 0 < hi

    def test_bootstrap_is_reproducible_with_seed(self):
        a = [0.1, 0.2, 0.3, 0.4]
        b = [0.2, 0.25, 0.3, 0.35]
        assert bootstrap_diff_ci(a, b, 500, seed=7) == bootstrap_diff_ci(a, b, 500, seed=7)

    def test_bootstrap_empty_inputs(self):
        assert bootstrap_diff_ci([], [1.0]) == (0.0, 0.0, 0.0)

    def test_cohens_d_sign_and_scale(self):
        a = [1.0, 1.1, 0.9, 1.05]
        b = [0.0, 0.1, -0.1, 0.05]
        assert cohens_d(a, b) > 3  # one SD apart by construction
        assert cohens_d(b, a) < 0
        assert cohens_d([1.0], [2.0]) == 0.0  # undefined -> 0