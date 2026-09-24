"""
Unit tests for entity_extractor.py.

Tests cover:
- Unit extraction (military, worker, settler)
- City extraction (growing, starving, happy, unhappy)
- Tech extraction (progress, prerequisites)
- Diplomacy extraction (war, neutral, allied)
- TotalDoF_index computation (Nash log-product)
- Psi declaration determinism
- Unknown entities (fog of war)
- Collapse source detection
"""
import math
import pytest

from env.entity_extractor import (
    EntityState,
    SystemStateMatrix,
    GameStateExtractor,
    compute_total_dof_index,
)
from env.config import EPSILON, TURN_DURATION_MKS


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures: synthetic CivRealm observations
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def extractor():
    """Default extractor instance."""
    return GameStateExtractor()


@pytest.fixture
def sample_observation():
    """Synthetic but realistic CivRealm observation."""
    return {
        'unit': {
            '103': {
                'type_rule_name': 'Settler',
                'health': 100,
                'moves_left': 2,
                'max_moves': 3,
                'x': 10,
                'y': 15,
                'owner': 0,
                'activity': 0,  # ACTIVITY_IDLE
            },
            '104': {
                'type_rule_name': 'Warrior',
                'health': 80,
                'moves_left': 1,
                'max_moves': 2,
                'x': 12,
                'y': 14,
                'owner': 0,
                'activity': 0,
            },
            '200': {
                'type_rule_name': 'Knight',
                'health': 50,
                'moves_left': 0,
                'max_moves': 3,
                'x': 20,
                'y': 20,
                'owner': 1,  # enemy unit
                'activity': 0,
            },
        },
        'city': {
            '1': {
                'population': 5,
                'food': 8,
                'production': 15,
                'gold': 40,
                'happiness': 2,
                'defense': 1,
                'x': 10,
                'y': 15,
                'owner': 0,
                'turn_last_built': 5,
                'prod_process': 10,
            },
            '2': {
                'population': 1,
                'food': -2,  # starving!
                'production': 3,
                'gold': 10,
                'happiness': -1,
                'defense': 0,
                'x': 25,
                'y': 30,
                'owner': 0,
                'turn_last_built': 1,
                'prod_process': 0,
            },
        },
        'tech': {
            '10': {
                'name': 'Bronze Working',
                'progress': 30,
                'prerequisites_met': 1,
                'total_prerequisites': 2,
            },
            '11': {
                'name': 'Writing',
                'progress': 0,
                'prerequisites_met': 0,
                'total_prerequisites': 1,
            },
        },
        'diplomacy': {
            '1': {
                'relationship': -0.5,  # hostile
                'alliance_options': [],
                'trade_options': ['gold'],
            },
            '2': {
                'relationship': 0.8,  # friendly
                'alliance_options': ['research_peace', 'alliance'],
                'trade_options': ['gold', 'tech', 'city'],
            },
        },
    }


@pytest.fixture
def sample_info():
    """Synthetic info dict."""
    return {
        'turn': 10,
        'available_actions': {
            'unit': {
                '103': {'build_city': True, 'goto_0': True},
                '104': {'goto_0': True, 'goto_1': True},
            },
            'city': {
                '1': {'build_unit': True, 'build_improvement': True},
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Unit extraction tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnitExtraction:
    """Test extraction of military and worker units."""

    def test_unit_count(self, extractor, sample_observation, sample_info):
        """Should extract all friendly and enemy units."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        # 3 units: 2 friendly + 1 enemy
        unit_entities = [e for e in result.state.entities if e.startswith('unit_')]
        assert len(unit_entities) == 3

    def test_unit_health_dof(self, extractor, sample_observation, sample_info):
        """Unit with lower health should have lower DoF."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        # Unit 104 has 80% health, unit 200 has 50% health
        dof_104 = result.state.entities['unit_104'].current_dof
        dof_200 = result.state.entities['unit_200'].current_dof
        assert dof_104 > dof_200

    def test_settler_autonomy(self, extractor, sample_observation, sample_info):
        """Settler is not autonomous (follows orders)."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        settler = result.state.entities['unit_103']
        assert settler.is_autonomous is False
        assert settler.agency_index < 0.3

    def test_unit_collapse_detection(self, extractor, sample_observation, sample_info):
        """Unit with very low health should have low time-to-collapse."""
        # Modify health to be critically low
        sample_observation['unit']['105'] = {
            'type_rule_name': 'Warrior',
            'health': 5,
            'moves_left': 0,
            'max_moves': 2,
            'x': 10,
            'y': 10,
            'owner': 0,
            'activity': 0,
        }
        result = extractor.extract(sample_observation, sample_info, turn=10)
        warrior = result.state.entities['unit_105']
        assert warrior.current_dof < 0.5
        assert warrior.time_to_collapse_mks < TURN_DURATION_MKS * 5


# ═══════════════════════════════════════════════════════════════════════════════
# City extraction tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCityExtraction:
    """Test extraction of cities."""

    def test_city_count(self, extractor, sample_observation, sample_info):
        """Should extract all cities."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        city_entities = [e for e in result.state.entities if e.startswith('city_')]
        assert len(city_entities) == 2

    def test_growing_city_higher_dof(self, extractor, sample_observation, sample_info):
        """Growing city should have higher DoF than starving city."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        growing = result.state.entities['city_1']
        starving = result.state.entities['city_2']
        assert growing.current_dof > starving.current_dof

    def test_starving_city_low_ttc(self, extractor, sample_observation, sample_info):
        """Starving city should have low time-to-collapse."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        starving = result.state.entities['city_2']
        assert starving.time_to_collapse_mks < TURN_DURATION_MKS * 10

    def test_city_autonomy(self, extractor, sample_observation, sample_info):
        """Cities are autonomous entities."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        city = result.state.entities['city_1']
        assert city.is_autonomous is True
        assert city.agency_index > 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# Tech extraction tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTechExtraction:
    """Test extraction of technology progress."""

    def test_tech_count(self, extractor, sample_observation, sample_info):
        """Should extract all technologies."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        tech_entities = [e for e in result.state.entities if e.startswith('tech_')]
        assert len(tech_entities) == 2

    def test_advanced_tech_higher_dof(self, extractor, sample_observation, sample_info):
        """Tech with more progress should have higher DoF."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        bronze = result.state.entities['tech_10']
        writing = result.state.entities['tech_11']
        assert bronze.current_dof > writing.current_dof

    def test_tech_not_autonomous(self, extractor, sample_observation, sample_info):
        """Technologies are not autonomous (researched by cities)."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        tech = result.state.entities['tech_10']
        assert tech.is_autonomous is False


# ═══════════════════════════════════════════════════════════════════════════════
# Diplomacy extraction tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiplomacyExtraction:
    """Test extraction of diplomatic relations."""

    def test_diplomacy_count(self, extractor, sample_observation, sample_info):
        """Should extract relations with other players (skip self)."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        dipl_entities = [e for e in result.state.entities if e.startswith('diplomacy_')]
        # Only 2 other players (player 0 is self, skipped)
        assert len(dipl_entities) == 2

    def test_friendly_higher_dof(self, extractor, sample_observation, sample_info):
        """Friendly relation should have higher DoF than hostile."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        friendly = result.state.entities['diplomacy_2']
        hostile = result.state.entities['diplomacy_1']
        assert friendly.current_dof > hostile.current_dof

    def test_diplomacy_autonomy(self, extractor, sample_observation, sample_info):
        """Diplomatic entities are autonomous."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        dipl = result.state.entities['diplomacy_1']
        assert dipl.is_autonomous is True


# ═══════════════════════════════════════════════════════════════════════════════
# TotalDoF_index tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTotalDofIndex:
    """Test Nash log-product index computation."""

    def test_positive_entities_positive_index(self, extractor, sample_observation, sample_info):
        """System with viable entities should have negative but finite index."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        index = compute_total_dof_index(result.state)
        # All entities have DoF > 0, so ln(DoF) < 0 → sum is negative
        assert index < 0
        assert math.isfinite(index)

    def test_more_entities_changes_index(self, extractor, sample_observation, sample_info):
        """Adding entities should change (increase magnitude of) the index."""
        result1 = extractor.extract(sample_observation, sample_info, turn=10)
        index1 = compute_total_dof_index(result1.state)

        # Add a new city
        sample_observation['city']['3'] = {
            'population': 8,
            'food': 12,
            'production': 20,
            'gold': 60,
            'happiness': 3,
            'defense': 2,
            'x': 15,
            'y': 20,
            'owner': 0,
            'turn_last_built': 8,
            'prod_process': 15,
        }
        result2 = extractor.extract(sample_observation, sample_info, turn=10)
        index2 = compute_total_dof_index(result2.state)

        # Adding an entity with DoF in (0, 1) makes ln(DoF) negative → index more negative
        assert index2 < index1  # more entities = more negative (lower) index


# ═══════════════════════════════════════════════════════════════════════════════
# Psi declaration tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPsiDeclaration:
    """Test determinism and structure of psi declaration."""

    def test_psi_has_id_and_digest(self, extractor, sample_observation, sample_info):
        """Psi declaration must contain id and digest."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        assert 'id' in result.state.psi
        assert 'digest' in result.state.psi

    def test_psi_digest_is_sha256(self, extractor, sample_observation, sample_info):
        """Digest must be a valid SHA-256 hex string (64 chars)."""
        result = extractor.extract(sample_observation, sample_info, turn=10)
        digest = result.state.psi['digest']
        assert len(digest) == 64
        assert all(c in '0123456789abcdef' for c in digest)

    def test_psi_digest_deterministic(self, extractor, sample_observation, sample_info):
        """Same input must produce same digest."""
        result1 = extractor.extract(sample_observation, sample_info, turn=10)
        result2 = extractor.extract(sample_observation, sample_info, turn=10)
        assert result1.state.psi['digest'] == result2.state.psi['digest']

    def test_psi_digest_changes_with_entities(self, extractor, sample_observation, sample_info):
        """Adding an entity must change the digest."""
        result1 = extractor.extract(sample_observation, sample_info, turn=10)
        sample_observation['city']['99'] = {
            'population': 10,
            'food': 20,
            'production': 30,
            'gold': 80,
            'happiness': 5,
            'defense': 3,
            'x': 30,
            'y': 30,
            'owner': 0,
            'turn_last_built': 1,
            'prod_process': 20,
        }
        result2 = extractor.extract(sample_observation, sample_info, turn=10)
        assert result1.state.psi['digest'] != result2.state.psi['digest']


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_observation(self, extractor):
        """Empty observation should produce valid empty state."""
        result = extractor.extract({}, {}, turn=0)
        assert len(result.state.entities) == 0
        index = compute_total_dof_index(result.state)
        assert index == 0.0  # no entities = 0

    def test_unit_no_moves(self, extractor):
        """Unit with no moves left should have lower mobility DoF."""
        obs = {
            'unit': {
                '1': {
                    'type_rule_name': 'Warrior',
                    'health': 100,
                    'moves_left': 0,
                    'max_moves': 2,
                    'x': 0,
                    'y': 0,
                    'owner': 0,
                    'activity': 0,
                },
                '2': {
                    'type_rule_name': 'Warrior',
                    'health': 100,
                    'moves_left': 2,
                    'max_moves': 2,
                    'x': 0,
                    'y': 0,
                    'owner': 0,
                    'activity': 0,
                },
            },
        }
        result = extractor.extract(obs, {}, turn=5)
        immobile = result.state.entities['unit_1'].current_dof
        mobile = result.state.entities['unit_2'].current_dof
        assert mobile > immobile

    def test_entity_dof_clamped(self, extractor):
        """DoF values must be clamped to [0, 1]."""
        obs = {
            'unit': {
                '1': {
                    'type_rule_name': 'Settler',
                    'health': 200,  # above 100%
                    'moves_left': 10,
                    'max_moves': 1,
                    'x': 0,
                    'y': 0,
                    'owner': 0,
                    'activity': 0,
                },
            },
        }
        result = extractor.extract(obs, {}, turn=1)
        dof = result.state.entities['unit_1'].current_dof
        assert 0.0 <= dof <= 1.0
