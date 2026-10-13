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

    def test_state_retains_positions_for_contextual_action_evidence(
            self, extractor, sample_observation, sample_info):
        result = extractor.extract(sample_observation, sample_info, turn=10)
        assert result.state.positions["unit_103"] == (10, 15)
        assert result.state.positions["city_1"] == (10, 15)
        assert result.state.positions["unit_200"] == (20, 20)


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
        """A unit down to its last hit point (1 HP of 10) is collapsing: low DoF
        and a one-turn time-to-collapse."""
        sample_observation['unit']['105'] = {
            'type_rule_name': 'Warrior',
            'health': 1,          # hit points, not percent (Warrior ceiling = 10)
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

    def test_known_tech_outranks_an_unknown_one(self, extractor, sample_observation,
                                                sample_info):
        """A technology is a gate: while unknown it is worth exactly one option
        (the possibility itself); once known it is worth what it unlocks. Two
        unknown technologies are therefore equal, and the previously used
        `progress` field — which the real observation does not even carry — no
        longer decides their value."""
        sample_observation['tech']['10']['inv_state'] = 1
        sample_observation['tech']['10']['sup_improvements'] = [
            {'name': 'Temple', 'build_cost': 30, 'upkeep': 1}]
        result = extractor.extract(sample_observation, sample_info, turn=10)
        known = result.state.entities['tech_10']
        unknown = result.state.entities['tech_11']
        assert known.dof_count > unknown.dof_count
        assert unknown.dof_count == pytest.approx(1.0)  # the possibility itself

    def test_tech_defers_to_the_same_unit_and_improvement_formulas(self, extractor):
        """A technology that has opened a strong unit is worth more than one that
        opened nothing, and its value is the sum of what it unlocked."""
        obs = {'tech': {
            '1': {'name': 'Advanced Flight', 'inv_state': 1,
                  'sup_units': [{'rule_name': 'Bomber', 'hp': 20, 'attack_strength': 12,
                                 'defense_strength': 1, 'firepower': 2, 'move_rate': 24,
                                 'vision_radius_sq': 2, 'build_cost': 120}],
                  'sup_improvements': []},
            '2': {'name': 'Chemistry', 'inv_state': 1, 'sup_units': [],
                  'sup_improvements': []},
        }}
        result = extractor.extract(obs, {}, turn=1)
        strong = result.state.entities['tech_1']
        empty = result.state.entities['tech_2']
        assert strong.dof_count > empty.dof_count == pytest.approx(1.0)

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
        """System with viable entities has a positive, finite index.

        DoF is an option count: each live entity contributes ln(count) and a
        well-equipped entity is worth more than one option, so the log-product is
        positive. (Under the old normalised scoring this was negative, which made
        the index decrease as the system grew.)
        """
        result = extractor.extract(sample_observation, sample_info, turn=10)
        index = compute_total_dof_index(result.state)
        assert index > 0
        assert math.isfinite(index)

    def test_more_entities_changes_index(self, extractor, sample_observation, sample_info):
        """Adding a live entity must NOT lower the index.

        DoF is an option count (>= 1), so a new city with options contributes a
        non-negative term. Scoring DoF as a normalised [0, 1] value instead made
        every added entity strictly reduce Σ ln(DoF) — which punished expansion
        (Axiom 1/6) and rewarded collapse.
        """
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

        assert index2 > index1  # a new entity with options raises the index


class TestPopulationEconomics:
    """Population is the DoF engine: a city must outrank a settler, a settler must
    not grow, and its people must erode while it wanders.

    The previous model had it backwards (size-1 city 0.105 vs settler 0.145), so
    founding a city measured as a DoF LOSS and the agent refused to expand.
    """

    @staticmethod
    def _unit(utype: str, health: int = 100, moves: int = 1, max_moves: int = 1):
        return {'unit': {'1': {
            'type_rule_name': utype, 'health': health, 'moves_left': moves,
            'max_moves': max_moves, 'x': 0, 'y': 0, 'owner': 0, 'activity': 0}}}

    @staticmethod
    def _city(pop: int, food: int = 0, production: int = 0, gold: int = 0,
              happiness: int = 0, defense: int = 0):
        return {'city': {'1': {
            'population': pop, 'food': food, 'production': production,
            'gold': gold, 'happiness': happiness, 'defense': defense,
            'x': 0, 'y': 0, 'owner': 0, 'turn_last_built': 0, 'prod_process': 0}}}

    def _dof_of(self, obs, turn=1):
        extractor = GameStateExtractor(my_player_id=0)
        result = extractor.extract(obs, {}, turn)
        return list(result.state.entities.values())[0].current_dof

    def _options_of(self, obs, turn=1):
        """Options (the authoritative DoF count) of the single extracted entity."""
        extractor = GameStateExtractor(my_player_id=0)
        result = extractor.extract(obs, {}, turn)
        return list(result.state.entities.values())[0].dof_count

    def test_settler_type_name_is_plural_in_the_ruleset(self, extractor):
        """Real rulesets name the founder "Settlers"; a singular-only match made
        the population model silently never apply."""
        from env.config import POPULATION_UNIT_TYPES

        assert "settlers" in POPULATION_UNIT_TYPES
        # Both spellings must be treated as population-carrying.
        for name in ("Settler", "Settlers", "settlers"):
            dof = self._dof_of(self._unit(name), 1)
            assert dof >= 0.10, name  # mobility bonus proves the branch applied

    def test_health_is_hit_points_not_percentage(self, extractor):
        """A real start state reports `Settlers health=20`, `Workers health=10`.
        Dividing by 100 made living units look collapsed."""
        full_hp_worker = self._dof_of(self._unit('Workers', health=10), 1)
        wounded_worker = self._dof_of(self._unit('Workers', health=3), 1)
        assert full_hp_worker > 0.25            # full HP is not "10% health"
        assert wounded_worker < full_hp_worker

    def test_null_max_moves_does_not_crash(self, extractor):
        """CivRealm nulls fields (``max_moves: null``) in some captures."""
        obs = {'unit': {'1': {'type_rule_name': 'Workers', 'health': 10,
                              'moves_left': None, 'max_moves': None,
                              'x': 0, 'y': 0, 'owner': 0, 'activity': 0}}}
        result = extractor.extract(obs, {}, 1)
        assert result.state.entities['unit_1'].current_dof > 0.0

    def test_future_components_come_from_real_flags(self, extractor):
        """The future component is read from the observation's own flags: a unit
        that can work terrain, convert, or carry others has more potential, and a
        population carrier has the largest future of all (it can found a city
        where population grows)."""
        from env.entity_extractor import unit_options

        def spec(**extra):
            obs = self._unit('Workers', health=10)
            obs['unit']['1'].update(extra)
            return obs['unit']['1']

        plain = unit_options(spec())[2]
        worker = unit_options(spec(type_worker=True))[2]
        converter = unit_options(spec(type_worker=False, type_converted_to=52,
                                      type_convert_time=1))[2]
        transport = unit_options(spec(type_worker=False, type_can_transport=True))[2]
        carrier = unit_options(spec(type_rule_name='Settlers', health=20,
                                    type_hp=20))[2]

        assert plain == 0.0            # an ordinary unit has no future component
        assert worker > plain          # terrain-changing potential
        assert converter > plain       # a conversion path
        assert transport > plain       # multiplying other units' options
        assert carrier > worker        # founding a city is the largest potential

    def test_city_outranks_settler(self, extractor):
        """A size-1 city is worth more than a fresh settler: the city is where
        population can grow. Compared in options — the authoritative count — since
        the [0, 1] score field is normalised against each entity's own ceiling."""
        assert self._options_of(self._city(1), 1) > self._options_of(self._unit('Settler'), 1)

    def test_city_dof_grows_with_population(self, extractor):
        small = self._options_of(self._city(1), 1)
        medium = self._options_of(self._city(4, food=6, production=6, happiness=2), 1)
        large = self._options_of(self._city(10, food=12, production=15, happiness=3,
                                            defense=2), 1)
        assert small < medium < large

    def test_unit_never_out_dofs_a_city(self, extractor):
        """A city is the population engine: even a modest working settlement holds
        more options than the best-armed unit, and a city's own ceiling (CITY_CEIL)
        is the higher one."""
        from env.config import CITY_CEIL, DOF_SCALE

        warrior = self._options_of(self._unit('Warrior', moves=3, max_moves=3), 1)
        city = self._options_of(
            self._city(1, food=0, production=5, happiness=1), 1)
        assert warrior <= DOF_SCALE < CITY_CEIL
        assert warrior < city

    def test_settler_people_decay_with_age(self, extractor):
        """Its people cannot grow; they only erode the longer it wanders."""
        extractor = GameStateExtractor(my_player_id=0)
        obs = self._unit('Settler')
        fresh = list(extractor.extract(obs, {}, 1).state.entities.values())[0]
        extractor.extract(obs, {}, 1)
        aged = list(extractor.extract(obs, {}, 40).state.entities.values())[0]
        assert aged.current_dof < fresh.current_dof

    def test_settler_decay_has_a_floor(self, extractor):
        """People remain even after a long time: the floor keeps it above zero."""
        from env.config import (CARRIER_DECAY_FLOOR, CARRIER_DECAY_PER_TURN,
                                DOF_SCALE, W_FUTURE_UNIT, UNIT_FUTURE_SETTLE_W)

        extractor = GameStateExtractor(my_player_id=0)
        obs = self._unit('Settler')
        extractor.extract(obs, {}, 1)
        ancient = list(extractor.extract(obs, {}, 500).state.entities.values())[0]
        assert ancient.dof_count > 0.0
        # The eroded floor of the future component, plus the live current one.
        floor_future = (W_FUTURE_UNIT * UNIT_FUTURE_SETTLE_W * CARRIER_DECAY_FLOOR)
        assert ancient.current_dof <= (0.15 + floor_future) + 1e-9
        assert CARRIER_DECAY_PER_TURN > 0.0

    def test_settler_is_risk_discounted(self, extractor):
        """A wounded settler in the field is worth less — it can be captured."""
        healthy = self._options_of(self._unit('Settler', health=100), 1)
        wounded = self._options_of(self._unit('Settler', health=40), 1)
        assert wounded < healthy

    def test_carrier_potential_dominates_its_own_total(self, extractor):
        """What makes a settler special is not its current capability but that its
        future component is nearly half of its value — an ordinary soldier's is a
        few per cent. That potential is realised by founding a city."""
        from env.entity_extractor import unit_options

        settler = self._unit('Settler')['unit']['1']
        # The real civ2civ3 Settlers also carry the worker and conversion flags.
        settler.update({'type_worker': True, 'type_converted_to': 52,
                        'type_convert_time': 1})
        soldier = self._unit('Warrior', health=10, moves=1, max_moves=1)['unit']['1']
        soldier.update({'type_attack_strength': 1, 'type_defense_strength': 1,
                        'type_firepower': 1, 'type_hp': 10})

        s_opts, s_cur, s_fut = unit_options(settler)
        w_opts, w_cur, w_fut = unit_options(soldier)
        assert s_fut > 0.4 and w_fut < 0.15                # potentials differ sharply
        assert w_cur > s_cur                               # soldier's CURRENT is higher
        # The carrier's value is mostly *potential*: nearly half of its options
        # come from what it can still become (a city), not from what it is.
        from env.config import DOF_SCALE, W_FUTURE_UNIT

        assert DOF_SCALE * W_FUTURE_UNIT * s_fut / s_opts > 0.4


class TestDofIndexScaling:
    """The index must count options, not normalised scores."""

    @staticmethod
    def _entity(entity_id: str, dof: float):
        from env.entity_extractor import EntityState

        return EntityState(entity_id=entity_id, current_dof=dof)

    def test_index_is_positive_for_live_entities(self):
        from env.entity_extractor import EntityState, SystemStateMatrix

        state = SystemStateMatrix(entities={
            'unit_1': self._entity('unit_1', 0.9),
            'city_1': self._entity('city_1', 0.5),
        })
        assert compute_total_dof_index(state) > 0

    def test_adding_an_entity_never_lowers_the_index(self):
        from env.entity_extractor import EntityState, SystemStateMatrix

        one = SystemStateMatrix(entities={'unit_1': self._entity('unit_1', 0.6)})
        two = SystemStateMatrix(entities={
            'unit_1': self._entity('unit_1', 0.6),
            'unit_2': self._entity('unit_2', 0.6),
        })
        assert compute_total_dof_index(two) > compute_total_dof_index(one)

    def test_entity_with_about_one_option_is_index_neutral(self):
        """An entity at the count-of-1 boundary contributes exactly ln(1)=0."""
        from env.config import DOF_SCALE
        from env.entity_extractor import EntityState, SystemStateMatrix

        state = SystemStateMatrix(entities={
            'unit_1': self._entity('unit_1', 1.0 / DOF_SCALE),
        })
        assert compute_total_dof_index(state) == pytest.approx(0.0, abs=1e-9)

    def test_collapsed_entity_is_catastrophic(self):
        from env.config import EPSILON
        from env.entity_extractor import EntityState, SystemStateMatrix

        healthy = SystemStateMatrix(
            entities={'unit_1': self._entity('unit_1', 0.5)})
        collapsing = SystemStateMatrix(
            entities={'unit_1': self._entity('unit_1', EPSILON)})

        assert compute_total_dof_index(collapsing) < compute_total_dof_index(healthy) - 10

    def test_collapse_source_is_excluded(self):
        from env.entity_extractor import EntityState, SystemStateMatrix

        state = SystemStateMatrix(entities={
            'unit_1': self._entity('unit_1', 0.5),
            'aggressor_1': EntityState(entity_id='aggressor_1', current_dof=0.9,
                                       is_collapse_source=True),
        })
        without = SystemStateMatrix(entities={'unit_1': self._entity('unit_1', 0.5)})
        assert compute_total_dof_index(state) == pytest.approx(
            compute_total_dof_index(without))


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
        """Spending this turn's moves must NOT lower a unit's DoF.

        Mobility is structural (max_moves), so a unit that has already used its
        movement retains the same future state space as a fresh one — otherwise a
        DoF-maximising agent would be forbidden from ever acting.
        """
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
        spent = result.state.entities['unit_1'].current_dof
        fresh = result.state.entities['unit_2'].current_dof
        assert spent == pytest.approx(fresh)

    def test_fewer_max_moves_lower_dof(self, extractor):
        """Structural movement capacity is what counts."""
        obs = {
            'unit': {
                '1': {'type_rule_name': 'Warrior', 'health': 100, 'moves_left': 1,
                      'max_moves': 1, 'x': 0, 'y': 0, 'owner': 0, 'activity': 0},
                '2': {'type_rule_name': 'Warrior', 'health': 100, 'moves_left': 1,
                      'max_moves': 3, 'x': 0, 'y': 0, 'owner': 0, 'activity': 0},
            },
        }
        result = extractor.extract(obs, {}, turn=5)
        slow = result.state.entities['unit_1'].current_dof
        fast = result.state.entities['unit_2'].current_dof
        assert fast > slow

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


# ═══════════════════════════════════════════════════════════════════════════════
# DoF must not be consumed by acting
#
# Regression: mobility was computed as moves_left / max_moves and can_retreat as
# moves_left > 0, so every action that spent a turn's movement lowered the unit's
# DoF. A DoF-maximising agent then refused to act at all, and when forced to act
# it strictly degraded the system index (-212.6 vs -205.1 for doing nothing in a
# 15-episode real tournament). Spending a renewable per-turn budget is not an
# irreversible loss of future state space.
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnitDofIsNotConsumedByActing:

    @staticmethod
    def _unit(moves_left: int, max_moves: int = 3, health: int = 100):
        return {
            'unit': {
                '7': {
                    'type_rule_name': 'Warrior',
                    'health': health,
                    'moves_left': moves_left,
                    'max_moves': max_moves,
                    'x': 1, 'y': 1, 'owner': 0, 'activity': 0,
                },
            },
        }

    def test_spending_moves_does_not_change_unit_dof(self, extractor):
        """Fresh unit and spent unit must score identically: the option to move
        next turn is intact either way."""
        fresh = extractor.extract(self._unit(moves_left=3), {}, turn=1)
        spent = extractor.extract(self._unit(moves_left=0), {}, turn=1)

        assert (fresh.state.entities['unit_7'].current_dof
                == pytest.approx(spent.state.entities['unit_7'].current_dof))

    def test_mobility_uses_structural_capacity(self, extractor):
        """A unit with more maximum moves keeps more DoF, regardless of what is
        left this turn."""
        fast = extractor.extract(self._unit(moves_left=0, max_moves=3), {}, turn=1)
        slow = extractor.extract(self._unit(moves_left=3, max_moves=1), {}, turn=1)

        assert (fast.state.entities['unit_7'].current_dof
                > slow.state.entities['unit_7'].current_dof)

    def test_zero_capacity_unit_keeps_its_components(self, extractor):
        """A unit with no movement capacity still has DoF from its other
        capabilities; it must not be driven to zero, and must stay below the
        settlement that produces population."""
        from env.config import CITY_CEIL, DOF_SCALE

        immobile = extractor.extract(self._unit(moves_left=0, max_moves=0), {}, turn=1)
        dof = immobile.state.entities['unit_7'].dof_count
        assert 0.5 < dof < DOF_SCALE
        city = extractor.extract(
            {'city': {'1': {'population': 1, 'food': 0, 'production': 0, 'gold': 0,
                            'happiness': 0, 'defense': 0, 'x': 0, 'y': 0,
                            'owner': 0, 'turn_last_built': 0, 'prod_process': 0}}},
            {}, turn=1)
        city_opts = city.state.entities['city_1'].dof_count
        assert dof < city_opts <= CITY_CEIL


class TestDofScalesWithHealth:
    """Мера владельца (§13.89): DoF сущности = базовый DoF × доля здоровья.

    Множитель — `health / type_hp`. Проверяется объявленное правило, а не
    подобранное число: при полном здоровье множитель нейтрален; нулевое здоровье
    даёт ровно ноль (без этого удар не может довести сущность до известного нуля
    и свидетеля §4.2 не будет); раненый юнит строго беднее здорового.
    """

    @staticmethod
    def _obs(health, ceiling=20):
        return {'unit': {'7': {'type_rule_name': 'Settlers', 'health': health,
                               'type_hp': ceiling, 'moves_left': 3,
                               'max_moves': 3, 'x': 10, 'y': 10, 'owner': 0}}}

    def test_ratio_comes_from_the_world_field(self):
        """Доля здоровья — из публикации мира: health / type_hp."""
        from env.entity_extractor import health_ratio

        assert health_ratio(self._obs(8)['unit']['7']) == pytest.approx(0.4)

    def test_full_health_is_neutral(self, extractor):
        """При полном здоровье мера DoF не двигает: множитель равен единице."""
        from env.entity_extractor import DOF_SCALE, unit_options

        full = extractor.extract(self._obs(20), {}, turn=1)
        base = unit_options(self._obs(20)['unit']['7'])[0] / DOF_SCALE
        assert full.state.entities['unit_7'].current_dof == pytest.approx(base)

    def test_zero_health_gives_exactly_zero(self, extractor):
        """Нулевое здоровье даёт DoF ровно ноль."""
        gone = extractor.extract(self._obs(0), {}, turn=1)
        assert gone.state.entities['unit_7'].current_dof == 0.0

    def test_a_wounded_unit_is_strictly_poorer(self, extractor):
        """Раненый юнит строго беднее здорового при том же прочем."""
        full = extractor.extract(self._obs(20), {}, turn=1)
        hurt = extractor.extract(self._obs(8), {}, turn=1)
        assert (hurt.state.entities['unit_7'].current_dof
                < full.state.entities['unit_7'].current_dof)
