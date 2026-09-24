"""
Unit tests for action_mapper.py and generator/heuristics.py.
"""
import pytest

from env.action_mapper import (
    CivAction,
    ActionOptionGenerator,
    classify_reversibility,
    estimate_dof_delta,
    estimate_resource_delta,
)
from env.entity_extractor import SystemStateMatrix, EntityState, GameStateExtractor
from brain.generator.heuristics import (
    DEFENSIVE,
    EXPANSIONIST,
    ECONOMIC,
    TECHNOLOGICAL,
    DIPLOMATIC,
    ALL_STRATEGIES,
    HeuristicGenerator,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Reversibility classification tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestReversibility:
    """Test action reversibility classification."""

    def test_irreversible_war(self):
        assert classify_reversibility('declare_war') is False

    def test_irreversible_attack(self):
        assert classify_reversibility('attack') is False

    def test_irreversible_disband(self):
        assert classify_reversibility('disband') is False

    def test_reversible_goto(self):
        assert classify_reversibility('goto') is True

    def test_reversible_fortify(self):
        assert classify_reversibility('fortify') is True

    def test_reversible_build_road(self):
        assert classify_reversibility('build_road') is True

    def test_partially_reversible_build_city(self):
        assert classify_reversibility('build_city') is False

    def test_goto_with_direction(self):
        """goto_0, goto_1 etc should be reversible."""
        assert classify_reversibility('goto_0') is True
        assert classify_reversibility('goto_5') is True

    def test_unknown_action_conservative(self):
        """Unknown actions default to reversible (safe)."""
        assert classify_reversibility('unknown_action_xyz') is True


# ═══════════════════════════════════════════════════════════════════════════════
# DoF delta estimation tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDofDelta:
    """Test DoF delta estimation."""

    @pytest.fixture
    def sample_state(self):
        return SystemStateMatrix(
            entities={
                'unit_103': EntityState(
                    entity_id='unit_103',
                    current_dof=0.6,
                ),
                'city_1': EntityState(
                    entity_id='city_1',
                    current_dof=0.7,
                ),
            },
        )

    def test_build_city_positive_delta(self, sample_state):
        action = CivAction(ctrl_type='unit', actor_id='103', action_name='build_city')
        delta = estimate_dof_delta(action, sample_state)
        assert 'unit_103' in delta
        assert delta['unit_103'] > 0  # creating settlement increases DoF

    def test_attack_negative_delta(self, sample_state):
        action = CivAction(ctrl_type='unit', actor_id='103', action_name='attack')
        delta = estimate_dof_delta(action, sample_state)
        assert 'unit_103' in delta
        assert delta['unit_103'] < 0  # risk of loss decreases DoF

    def test_goto_small_positive_delta(self, sample_state):
        action = CivAction(ctrl_type='unit', actor_id='103', action_name='goto_3')
        delta = estimate_dof_delta(action, sample_state)
        assert 'unit_103' in delta
        assert delta['unit_103'] > 0
        assert delta['unit_103'] < 0.1  # small effect

    def test_city_build_unit_positive_delta(self, sample_state):
        action = CivAction(ctrl_type='city', actor_id='1', action_name='build_unit')
        delta = estimate_dof_delta(action, sample_state)
        assert 'city_1' in delta
        assert delta['city_1'] > 0

    def test_war_negative_delta(self, sample_state):
        state = SystemStateMatrix(
            entities={
                'diplomacy_2': EntityState(
                    entity_id='diplomacy_2',
                    current_dof=0.5,
                ),
            },
        )
        action = CivAction(ctrl_type='diplomacy', actor_id='2', action_name='declare_war')
        delta = estimate_dof_delta(action, state)
        assert 'diplomacy_2' in delta
        assert delta['diplomacy_2'] < 0


# ═══════════════════════════════════════════════════════════════════════════════
# Resource delta estimation tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestResourceDelta:
    """Test resource delta estimation."""

    def test_city_build_unit_consumes_production(self):
        action = CivAction(ctrl_type='city', actor_id='1', action_name='build_unit')
        delta = estimate_resource_delta(action)
        assert 'city_1' in delta
        assert delta['city_1'].get('production', 0) < 0

    def test_city_research_consumes_bulbs(self):
        action = CivAction(ctrl_type='city', actor_id='1', action_name='research_tech')
        delta = estimate_resource_delta(action)
        assert 'city_1' in delta
        assert delta['city_1'].get('bulbs', 0) < 0

    def test_unit_build_city_consumes_production(self):
        action = CivAction(ctrl_type='unit', actor_id='103', action_name='build_city')
        delta = estimate_resource_delta(action)
        assert 'unit_103' in delta
        assert delta['unit_103'].get('production', 0) < 0

    def test_goto_no_resource_cost(self):
        action = CivAction(ctrl_type='unit', actor_id='103', action_name='goto_3')
        delta = estimate_resource_delta(action)
        assert delta == {}  # no resource cost for movement


# ═══════════════════════════════════════════════════════════════════════════════
# ActionOption generation tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestActionOptionGenerator:
    """Test generation of ActionOption candidates."""

    @pytest.fixture
    def generator(self):
        return ActionOptionGenerator()

    @pytest.fixture
    def sample_state(self):
        return SystemStateMatrix(
            entities={
                'unit_103': EntityState(entity_id='unit_103', current_dof=0.6),
                'city_1': EntityState(entity_id='city_1', current_dof=0.7),
            },
        )

    @pytest.fixture
    def sample_available(self):
        return {
            'unit': {
                '103': {'build_city': True, 'goto_0': True, 'fortify': True},
            },
            'city': {
                '1': {'build_unit': True, 'research_tech': True},
            },
        }

    def test_generates_candidates(self, generator, sample_state, sample_available):
        candidates = generator.generate_from_state(sample_state, sample_available)
        assert len(candidates) > 0

    def test_unit_actions_mapped(self, generator, sample_state, sample_available):
        candidates = generator.generate_from_state(sample_state, sample_available)
        unit_opts = [c for c in candidates if c['option_id'].startswith('unit_')]
        assert len(unit_opts) == 3  # build_city, goto_0, fortify

    def test_city_actions_mapped(self, generator, sample_state, sample_available):
        candidates = generator.generate_from_state(sample_state, sample_available)
        city_opts = [c for c in candidates if c['option_id'].startswith('city_')]
        assert len(city_opts) == 2  # build_unit, research_tech

    def test_all_have_option_id(self, generator, sample_state, sample_available):
        candidates = generator.generate_from_state(sample_state, sample_available)
        for c in candidates:
            assert 'option_id' in c
            assert 'description' in c
            assert 'is_reversible' in c

    def test_irreversible_marked(self, generator, sample_state):
        available = {
            'unit': {
                '103': {'attack': True, 'declare_war': True},
            },
        }
        candidates = generator.generate_from_state(sample_state, available)
        for c in candidates:
            if 'attack' in c['option_id']:
                assert c['is_reversible'] is False

    def test_empty_available_returns_empty(self, generator, sample_state):
        candidates = generator.generate_from_state(sample_state, {})
        assert candidates == []


# ═══════════════════════════════════════════════════════════════════════════════
# Heuristic generator tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestHeuristicGenerator:
    """Test heuristic strategy-based generation."""

    @pytest.fixture
    def sample_state(self):
        return SystemStateMatrix(
            entities={
                'unit_103': EntityState(entity_id='unit_103', current_dof=0.6),
                'city_1': EntityState(entity_id='city_1', current_dof=0.7),
            },
        )

    @pytest.fixture
    def sample_available(self):
        return {
            'unit': {
                '103': {'build_city': True, 'goto_0': True, 'fortify': True, 'attack': True},
            },
            'city': {
                '1': {'build_unit': True, 'research_tech': True, 'buy_unit': True},
            },
            'diplomacy': {
                '2': {'peace_treaty': True, 'declare_war': True},
            },
        }

    def test_all_strategies_exist(self):
        assert len(ALL_STRATEGIES) == 5
        names = {s.name for s in ALL_STRATEGIES}
        assert 'defensive' in names
        assert 'expansionist' in names
        assert 'economic' in names
        assert 'technological' in names
        assert 'diplomatic' in names

    def test_defensive_prioritizes_fortify(self, sample_state, sample_available):
        gen = HeuristicGenerator(strategy=DEFENSIVE)
        candidates = gen.generate_candidates(sample_state, sample_available)
        assert len(candidates) > 0
        # Fortify should appear before attack
        fortify_idx = next((i for i, c in enumerate(candidates) if 'fortify' in c['option_id']), -1)
        attack_idx = next((i for i, c in enumerate(candidates) if 'attack' in c['option_id']), -1)
        if fortify_idx >= 0 and attack_idx >= 0:
            assert fortify_idx < attack_idx

    def test_expansionist_prioritizes_build_city(self, sample_state, sample_available):
        gen = HeuristicGenerator(strategy=EXPANSIONIST)
        candidates = gen.generate_candidates(sample_state, sample_available)
        assert len(candidates) > 0
        assert any('build_city' in c['option_id'] for c in candidates[:3])

    def test_economic_prioritizes_trade(self, sample_state):
        available = {
            'city': {'1': {'build_improvement': True}},
            'diplomacy': {'2': {'trade_agreement': True}},
        }
        gen = HeuristicGenerator(strategy=ECONOMIC)
        candidates = gen.generate_candidates(sample_state, available)
        assert len(candidates) > 0

    def test_returns_max_5_candidates(self, sample_state, sample_available):
        gen = HeuristicGenerator()
        candidates = gen.generate_candidates(sample_state, sample_available)
        assert len(candidates) <= 5

    def test_select_best_returns_highest_dof(self, sample_state, sample_available):
        gen = HeuristicGenerator()
        candidates = gen.generate_candidates(sample_state, sample_available)
        best = gen.select_best(candidates, sample_state)
        assert best is not None
        assert 'projected_dof_delta' in best

    def test_select_best_empty_returns_none(self, sample_state):
        gen = HeuristicGenerator()
        assert gen.select_best([], sample_state) is None
