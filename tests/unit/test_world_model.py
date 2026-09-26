"""
Tests for the agent's world model and its refinement loop.

The point of these tests is the stated design rule: **"reality is primary"**.
The model is pre-installed and largely matches the world, but whenever the world
reports something else, the world wins — as long as the report is at least as
trustworthy as what the model already claims. And every correction must be
journaled, reversible, and must actually reach the formulas the agent decides
with.
"""
import ast
import re
import pathlib

import pytest

from env.config import CITY_BASE, DOF_SCALE, UNIT_ATTACK_REF
from env.entity_extractor import (
    GameStateExtractor, city_options, unit_options,
)
from env.world_model import (
    ModelEntry, Provenance, STRENGTH, WorldModel, default_model,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def model() -> WorldModel:
    return WorldModel.from_config()


@pytest.fixture
def sample_observation() -> dict:
    """The real captured start state (city + units + technologies)."""
    recs = __import__('json').load(
        open('tests/fixtures/real_obs_01.json'))
    return recs[0]['observation']


# ═══════════════════════════════════════════════════════════════════════════════
# Priors and provenance
# ═══════════════════════════════════════════════════════════════════════════════

class TestPriors:
    def test_priors_are_loaded_with_provenance(self, model):
        """Every entry says where it came from: the world may only overwrite what
        it is at least as trustworthy as."""
        assert model.get('CITY_BASE') == CITY_BASE
        assert model.source_of('CITY_BASE') is Provenance.ASSUMED
        assert model.get('city.granary_per_size') == 10.0
        assert model.source_of('city.granary_per_size') is Provenance.RULESET

    def test_trust_ordering(self):
        assert STRENGTH[Provenance.RULESET] > STRENGTH[Provenance.MEASURED]
        assert STRENGTH[Provenance.MEASURED] > STRENGTH[Provenance.ASSUMED]

    def test_values_snapshot_matches_get(self, model):
        vals = model.values()
        assert vals['W_FUTURE_UNIT'] == model.get('W_FUTURE_UNIT')


# ═══════════════════════════════════════════════════════════════════════════════
# The refinement loop
# ═══════════════════════════════════════════════════════════════════════════════

class TestRefinement:
    def test_agreeing_observation_verifies_without_correction(self, model):
        rec = model.observe('city.radius_sq', 5.0, turn=1)
        assert rec.verdict == 'match'
        entry = model.entries['city.radius_sq']
        assert entry.verified_turn == 1
        assert entry.revision == 0
        assert model.corrections() == []

    def test_world_corrects_a_wrong_claim(self, model):
        """The stand says the granary rule is not what the documentation claimed."""
        rec = model.observe('city.granary_per_size', 12.0, turn=3,
                            evidence='granary_size=36 at size 2')
        assert rec.verdict == 'corrected'
        assert model.get('city.granary_per_size') == 12.0
        entry = model.entries['city.granary_per_size']
        assert entry.revision == 1
        assert entry.history[-1]['old'] == 10.0
        assert entry.history[-1]['new'] == 12.0

    def test_two_assumptions_never_overwrite_each_other(self, model):
        """A guess is not evidence about another guess: it goes to `pending`."""
        rec = model.observe('CITY_BASE', 3.0, turn=2, source=Provenance.ASSUMED,
                            evidence='another guess')
        assert rec.verdict == 'pending'
        assert model.get('CITY_BASE') == CITY_BASE
        assert model.entries['CITY_BASE'].revision == 0

    def test_measurement_overrides_an_assumption(self, model):
        rec = model.observe('W_FUTURE_UNIT', 0.60, turn=4,
                            source=Provenance.MEASURED, evidence='fit over 30 pairs')
        assert rec.verdict == 'corrected'
        assert model.get('W_FUTURE_UNIT') == 0.60
        assert model.source_of('W_FUTURE_UNIT') is Provenance.MEASURED

    def test_assumption_cannot_overwrite_a_measurement(self, model):
        model.observe('W_FUTURE_UNIT', 0.60, turn=4, source=Provenance.MEASURED)
        rec = model.observe('W_FUTURE_UNIT', 0.10, turn=5, source=Provenance.ASSUMED)
        assert rec.verdict == 'pending'
        assert model.get('W_FUTURE_UNIT') == 0.60

    def test_unknown_key_is_registered_as_a_new_fact(self, model):
        rec = model.observe('unit_type.knights.attack_strength', 5, turn=7)
        assert rec.verdict == 'new'
        assert model.get('unit_type.knights.attack_strength') == 5

    def test_corrections_are_reversible(self, model):
        model.observe('city.radius_sq', 7.0, turn=3, evidence='observed')
        assert model.get('city.radius_sq') == 7.0
        assert model.revert('city.radius_sq') is True
        assert model.get('city.radius_sq') == 5.0

    def test_corrected_value_reaches_the_formulas(self, model):
        """The whole point: a correction must change what the agent computes."""
        city = {'size': 1, 'surplus_food': 0, 'food_stock': 0, 'granary_size': 20,
                'improvements': [], 'surplus_shield': 0, 'surplus_trade': 0,
                'surplus_gold': 0, 'science': 0, 'luxury': 0,
                'ppl_happy': 0, 'ppl_unhappy': 0, 'ppl_angry': 0}
        before = city_options(city, model=model)
        model.observe('CITY_BASE', CITY_BASE + 1.0, turn=1, source=Provenance.MEASURED,
                      evidence='fit')
        after = city_options(city, model=model)
        assert after == pytest.approx(before + 1.0 * 1.0)

        unit = {'type_rule_name': 'Warrior', 'health': 10, 'type_hp': 10,
                'type_attack_strength': 10, 'type_defense_strength': 0,
                'type_firepower': 0, 'type_move_rate': 0, 'type_vision_radius_sq': 0}
        before_unit = unit_options(unit, model=model)[0]
        model.observe('UNIT_ATTACK_REF', UNIT_ATTACK_REF * 2, turn=1,
                      source=Provenance.MEASURED, evidence='fit')
        assert unit_options(unit, model=model)[0] != pytest.approx(before_unit)

    def test_audit_summary(self, model):
        model.observe('city.radius_sq', 5.0, turn=1)          # match
        model.observe('city.granary_per_size', 12.0, turn=2)  # correction
        summary = model.summary()
        assert summary['verdicts'].get('match') == 1
        assert summary['verdicts'].get('corrected') == 1
        assert summary['corrections'] == 1
        assert summary['entries_by_source']['assumed'] > 0

    def test_mismatches_are_visible(self, model):
        model.observe('city.radius_sq', 5.0, turn=1)
        model.observe('city.granary_per_size', 12.0, turn=2)
        keys = [r.key for r in model.mismatches()]
        assert keys == ['city.granary_per_size']


# ═══════════════════════════════════════════════════════════════════════════════
# Coefficients: statistics only, never a single sighting
# ═══════════════════════════════════════════════════════════════════════════════

class TestStatisticalRefinement:
    def test_a_single_pair_changes_nothing(self, model):
        model.record_pair('CITY_POP', predicted=1.0, observed=2.0, turn=1)
        assert model.refine_coefficient('CITY_POP') is None
        assert model.get('CITY_POP') == 1.0

    def test_fit_applies_after_enough_pairs(self, model):
        for turn in range(8):
            model.record_pair('CITY_POP', predicted=1.0, observed=1.5, turn=turn)
        assert model.stat_pairs('CITY_POP') == 8
        assert model.refine_coefficient('CITY_POP', min_n=5) == pytest.approx(1.5)
        assert model.source_of('CITY_POP') is Provenance.MEASURED

    def test_tiny_change_is_not_applied(self, model):
        for turn in range(8):
            model.record_pair('CITY_POP', predicted=1.0, observed=1.0, turn=turn)
        assert model.refine_coefficient('CITY_POP', min_n=5) is None
        assert model.get('CITY_POP') == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# The extractor's reconciliation pass
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractorReconciliation:
    def test_preinstalled_model_agrees_with_the_real_stand(self, sample_observation):
        """The honest measurement behind "largely agrees": on the real captured
        state, every rule the model claims is confirmed by the world."""
        extractor = GameStateExtractor(my_player_id=0)
        extractor.extract(sample_observation, {}, turn=1)
        model = extractor.model

        assert model.summary()['verdicts'].get('corrected', 0) == 0
        checked = {r.key: r for r in model.reconciliations}
        assert checked['city.radius_sq'].verdict == 'match'
        assert checked['city.granary_per_size'].verdict == 'match'
        # hit points of the unit types the model claims
        assert checked['unit_type.settlers.hp'].verdict == 'match'
        assert checked['unit_type.workers.hp'].verdict == 'match'
        assert checked['unit_type.explorer.hp'].verdict == 'match'
        assert model.entries['unit_type.settlers.hp'].verified_turn == 1

    def test_new_unit_type_facts_are_learned_from_the_world(self, sample_observation):
        extractor = GameStateExtractor(my_player_id=0)
        extractor.extract(sample_observation, {}, turn=1)
        model = extractor.model
        # parameters the documentation never listed, now recorded as facts
        assert model.get('unit_type.settlers.build_cost') == 40
        assert model.get('unit_type.settlers.attack_strength') == 0
        assert model.get('unit_type.workers.move_rate') == 3
        assert model.source_of('unit_type.workers.move_rate') is Provenance.RULESET

    def test_instance_facts_are_never_written_into_the_model(self, sample_observation):
        """A city's SIZE is state, not model knowledge: caching it is exactly the
        bug that made the bridge estimate a future city from an existing one."""
        extractor = GameStateExtractor(my_player_id=0)
        extractor.extract(sample_observation, {}, turn=1)
        keys = list(extractor.model.entries)
        instance_like = [k for k in keys
                         if re.match(r'^(city|unit|tech|diplomacy)_\d', k)]

        assert instance_like == []                     # no entity-instance ids
        assert not any(k.endswith('.size') for k in keys)

    def test_model_is_shared_with_the_bridge_formulas(self, sample_observation):
        """The extractor's model is the one the formulas read, so a correction
        the world imposes is used by the very next extraction."""
        extractor = GameStateExtractor(my_player_id=0)
        first = extractor.extract(sample_observation, {}, turn=1)
        city_before = first.state.entities['city_121'].dof_count

        extractor.model.observe('CITY_M1_IMPROV', 0.0, turn=1,
                                source=Provenance.MEASURED,
                                evidence='test: improvement weight removed')
        second = extractor.extract(sample_observation, {}, turn=2)
        assert second.state.entities['city_121'].dof_count < city_before

    def test_default_model_is_a_fallback_not_the_agents_model(self, sample_observation):
        """Free functions keep working without an explicit model (scripts), but
        the decision path uses the agent's own instance."""
        extractor = GameStateExtractor(my_player_id=0)
        assert extractor.model is not default_model()
        assert city_options({'size': 1}) == city_options({'size': 1},
                                                         model=default_model())


class TestNoHiddenConstants:
    """The formulas must read the model, not module constants."""

    def test_formula_bodies_reference_the_model_snapshot(self):
        src = pathlib.Path('env/entity_extractor.py').read_text()
        tree = ast.parse(src)
        wanted = {'unit_options', 'improvement_options', 'city_options', 'tech_options'}
        checked = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in wanted:
                checked += 1
                body = ast.get_source_segment(src, node) or ''
                assert "vals['" in body, f'{node.name} does not read the model'
        assert checked == len(wanted)

    def test_city_and_unit_weights_are_not_read_directly(self):
        """The calibration weights live in the model; the formulas may only touch
        them through its snapshot."""
        src = pathlib.Path('env/entity_extractor.py').read_text()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name == 'city_options':
                body = ast.get_source_segment(src, node) or ''
                for const in ('CITY_M1_FOOD', 'CITY_M2_GOLD', 'CITY_HAPPY_W'):
                    assert f"vals['{const}']" in body
                    assert f" {const} *" not in body
