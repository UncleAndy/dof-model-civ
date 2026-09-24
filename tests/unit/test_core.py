"""Unit tests for the DOFCalculusCore Rust engine (via PyO3).

Verifies:
- Core instantiation
- Nash log-product index computation
- Best action selection
- Axiom 3 veto (non-compensation)
- Axiom 5 uncertainty (epsilon floor)
"""
import pytest
import math

from dof_core import (
    DOFCalculusCore,
    CoreEntity,
    CoreAction,
    CoreDecision,
)


class TestCoreBasics:
    """Test core instantiation and basic properties."""

    def test_create_default(self):
        core = DOFCalculusCore()
        assert core.lookahead_horizon == 3
        assert core.context_switch_penalty == 0.5

    def test_create_custom(self):
        core = DOFCalculusCore(lookahead_horizon=5, context_switch_penalty=1.0)
        assert core.lookahead_horizon == 5
        assert core.context_switch_penalty == 1.0


class TestNashIndex:
    """Test Nash log-product index computation."""

    def test_empty_state(self):
        core = DOFCalculusCore()
        index = core.compute_index([])
        assert index == 0.0

    def test_single_entity(self):
        core = DOFCalculusCore()
        state = [CoreEntity("city_1", 0.5)]
        index = core.compute_index(state)
        assert math.isclose(index, math.log(0.5), abs_tol=1e-6)

    def test_multiple_entities(self):
        core = DOFCalculusCore()
        state = [
            CoreEntity("city_1", 0.5),
            CoreEntity("city_2", 0.7),
        ]
        index = core.compute_index(state)
        expected = math.log(0.5) + math.log(0.7)
        assert math.isclose(index, expected, abs_tol=1e-6)

    def test_collapse_source_excluded(self):
        core = DOFCalculusCore()
        state = [
            CoreEntity("city_1", 0.5, is_collapse_source=False),
            CoreEntity("aggressor", 0.9, is_collapse_source=True),
        ]
        index = core.compute_index(state)
        # aggressor excluded from index
        assert math.isclose(index, math.log(0.5), abs_tol=1e-6)

    def test_dof_floored_at_epsilon(self):
        """Axiom 5: DoF floored at epsilon inside logarithm."""
        core = DOFCalculusCore()
        state = [CoreEntity("city_1", 0.0)]  # collapsed
        index = core.compute_index(state)
        # Should be ln(epsilon), not -inf
        assert math.isfinite(index)
        assert math.isclose(index, math.log(1e-6), abs_tol=1e-6)


class TestBestSelection:
    """Test best action selection."""

    def test_empty_candidates_returns_none(self):
        core = DOFCalculusCore()
        state = [CoreEntity("city_1", 0.5)]
        result = core.select_best(state, [])
        assert result.chosen_action_id is None

    def test_single_candidate(self):
        core = DOFCalculusCore()
        state = [CoreEntity("city_1", 0.5)]
        candidates = [CoreAction("act_1", "Test action", [("city_1", 0.1)])]
        result = core.select_best(state, candidates)
        assert result.chosen_action_id == "act_1"

    def test_selects_highest_dof_gain(self):
        core = DOFCalculusCore()
        state = [CoreEntity("city_1", 0.5)]
        candidates = [
            CoreAction("low_gain", "Low gain", [("city_1", 0.01)]),
            CoreAction("high_gain", "High gain", [("city_1", 0.2)]),
        ]
        result = core.select_best(state, candidates)
        assert result.chosen_action_id == "high_gain"

    def test_negative_delta_stays_put(self):
        """If all actions reduce DoF, stay put."""
        core = DOFCalculusCore()
        state = [CoreEntity("city_1", 0.5)]
        candidates = [
            CoreAction("harmful", "Harmful", [("city_1", -0.1)]),
        ]
        result = core.select_best(state, candidates)
        # Negative delta should result in no action chosen
        assert result.chosen_action_id is None

    def test_audit_populated(self):
        core = DOFCalculusCore()
        state = [CoreEntity("city_1", 0.5)]
        candidates = [
            CoreAction("act_1", "Action 1", [("city_1", 0.1)]),
            CoreAction("act_2", "Action 2", [("city_1", 0.05)]),
        ]
        result = core.select_best(state, candidates)
        assert len(result.audit) == 2


class TestAxiom3Veto:
    """Test Axiom 3 (Non-Compensation) veto."""

    def test_collapse_reversible_entity_vetoed(self):
        """A branch that collapses a reversible entity should be vetoed."""
        core = DOFCalculusCore(lookahead_horizon=1)
        # Entity that is revivable and currently healthy
        state = [
            CoreEntity("city_1", 0.5, is_reversible=True),
            CoreEntity("city_2", 0.7, is_reversible=True),
        ]
        # Action that would collapse city_1 (push to 0)
        harmful = CoreAction(
            "harm_city_1",
            "Harm city_1",
            [("city_1", -1.0)],  # push from 0.5 to 0 (collapse)
            is_reversible=False,
        )
        # Safe action
        safe = CoreAction(
            "safe",
            "Safe action",
            [("city_2", 0.1)],
            is_reversible=True,
        )
        result = core.select_best(state, [harmful, safe])
        # Safe should be chosen; harmful should be vetoed
        assert result.chosen_action_id == "safe"

    def test_audit_marks_vetoed(self):
        core = DOFCalculusCore(lookahead_horizon=1)
        state = [CoreEntity("city_1", 0.3, is_reversible=True)]
        harmful = CoreAction(
            "destroy",
            "Destroy city",
            [("city_1", -1.0)],
            is_reversible=False,
        )
        result = core.select_best(state, [harmful])
        # The harmful action should be marked as vetoed
        for action_id, score, vetoed in result.audit:
            if action_id == "destroy":
                assert vetoed is True

    def test_aggressor_not_vetoed(self):
        """Collapse source entities are not protected by veto."""
        core = DOFCalculusCore(lookahead_horizon=1)
        state = [
            CoreEntity("city_1", 0.5, is_collapse_source=False),
            CoreEntity("aggressor_1", 0.6, is_collapse_source=True),
        ]
        # Action that reduces aggressor (not vetoed)
        action = CoreAction(
            "contain_aggressor",
            "Contain aggressor",
            [("aggressor_1", -0.2)],
            is_reversible=False,
        )
        result = core.select_best(state, [action])
        assert result.chosen_action_id == "contain_aggressor"
