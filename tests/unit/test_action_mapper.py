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
import env.action_mapper as action_mapper_module


@pytest.fixture(autouse=True)
def ignore_persistent_wedge_registry(monkeypatch):
    """Keep runtime wedge evidence from changing projection unit-test fixtures."""
    monkeypatch.setattr(action_mapper_module, "is_wedged", lambda *_, **__: False)


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
    """DoF delta estimation, in options, from the calibrated model."""

    @pytest.fixture
    def sample_state(self):
        from env.entity_extractor import BridgeCalibration

        return SystemStateMatrix(
            entities={
                'unit_103': EntityState(
                    entity_id='unit_103', current_dof=0.38, dof_options=3.81),
                'city_1': EntityState(
                    entity_id='city_1', current_dof=0.41, dof_options=8.14),
                'tech_2': EntityState(
                    entity_id='tech_2', current_dof=0.10, dof_options=1.0),
            },
            bridge=BridgeCalibration(
                new_city_options=4.85,
                improvement_gain={'city_1': 2.33},
                unit_type_options={'Bomber': 6.54, 'Settlers': 3.81},
                improvement_options={'Temple': 1.40},
                tech_research_gain={'tech_2': 1.85},
            ),
        )

    def test_founding_is_a_derived_gain(self, sample_state):
        """Founding exchanges the settler for a size-1 city, so the delta is the
        difference between them in THIS state — a gain, because a city is where
        population (the DoF engine) grows. A constant measured under the old
        model (-0.3228) would have kept the old, inverted incentive."""
        action = CivAction(ctrl_type='unit', actor_id='103', action_name='found_city')
        delta = estimate_dof_delta(action, sample_state)
        assert delta['unit_103'] == pytest.approx(4.85 - 3.81)

    def test_unmeasured_actions_get_no_invented_number(self, sample_state):
        """`attack` was guessed at -0.1. There is no measurement and no structural
        derivation for it, so it must project nothing at all: the modelled cost of
        an attack is its irreversibility, applied by the core on that flag."""
        delta = estimate_dof_delta(
            CivAction(ctrl_type='unit', actor_id='103', action_name='attack'), sample_state)
        assert delta == {}
        assert classify_reversibility('attack') is False

    def test_goto_is_measured_neutral(self, sample_state):
        """`goto` was guessed at +0.01; measured on a live game it changes
        nothing in the index (Δindex = 0.0000). После перевода весов города на
        числа встроенного ИИ (§13.186) ход не даёт записи вовсе — это тот же
        нейтральный исход, что и отсутствие изменения."""
        action = CivAction(ctrl_type='unit', actor_id='103', action_name='goto_3')
        delta = estimate_dof_delta(action, sample_state)
        assert delta.get('unit_103', 0.0) == pytest.approx(0.0)

    def test_fortify_is_measured_neutral(self, sample_state):
        action = CivAction(ctrl_type='unit', actor_id='103', action_name='fortify')
        delta = estimate_dof_delta(action, sample_state)
        assert delta['unit_103'] == pytest.approx(0.0)

    def test_producing_a_unit_adds_its_options(self, sample_state):
        """`produce_Bomber` creates a new entity with its own option space, priced
        by the same unit formula from the observation's own type catalogue."""
        action = CivAction(ctrl_type='city', actor_id='1', action_name='produce_Bomber')
        delta = estimate_dof_delta(action, sample_state)
        assert delta['city_1'] == pytest.approx(6.54)

    def test_producing_an_improvement_raises_the_city_factor(self, sample_state):
        action = CivAction(ctrl_type='city', actor_id='1', action_name='produce_Temple')
        delta = estimate_dof_delta(action, sample_state)
        assert delta['city_1'] == pytest.approx(2.33)

    def test_selling_an_improvement_costs_the_same_gain(self, sample_state):
        action = CivAction(ctrl_type='city', actor_id='1',
                           action_name='city_sell_improvement_Temple')
        delta = estimate_dof_delta(action, sample_state)
        assert delta['city_1'] == pytest.approx(-2.33)

    def test_research_prices_what_the_technology_unlocks(self, sample_state):
        action = CivAction(ctrl_type='tech', actor_id='cur_player',
                           action_name='research_tech_Alphabet_2')
        delta = estimate_dof_delta(action, sample_state)
        assert delta['tech_2'] == pytest.approx(1.85)

    def test_war_has_no_invented_delta(self, sample_state):
        """Declaring war is unmeasured as a DoF change; what the model knows about
        it is that it is irreversible."""
        action = CivAction(ctrl_type='dipl', actor_id='2', action_name='declare_war')
        assert estimate_dof_delta(action, sample_state) == {}
        assert classify_reversibility('declare_war') is False


# ═══════════════════════════════════════════════════════════════════════════════
# Resource delta estimation tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestResourceDelta:
    """Test resource delta estimation."""

    def test_city_production_order_consumes_production(self):
        action = CivAction(ctrl_type='city', actor_id='1', action_name='produce_Bomber')
        delta = estimate_resource_delta(action)
        assert 'city_1' in delta
        assert delta['city_1'].get('production', 0) < 0

    def test_city_buy_production_consumes_gold(self):
        action = CivAction(ctrl_type='city', actor_id='1',
                           action_name='city_buy_production')
        delta = estimate_resource_delta(action)
        assert 'city_1' in delta
        assert delta['city_1'].get('gold', 0) < 0

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

    def test_dominated_branch_is_excluded_from_shortlist(self, sample_state, sample_available):
        """Founding (measured -0.32) is dominated by better branches, so it is
        not offered; offering a dominated branch would only waste a slot."""
        gen = HeuristicGenerator(strategy=EXPANSIONIST)
        candidates = gen.generate_candidates(sample_state, sample_available)
        assert len(candidates) > 0
        gains = [sum(c['projected_dof_delta'].values()) for c in candidates]
        assert min(gains) > -0.3228, (
            "a worse-than-founding branch was shortlisted while founding was not")

    def test_founding_is_shortlisted_when_it_is_best_available(self, sample_state):
        """With only founding and a neutral move available, both kinds must appear
        so DOF-Core can weigh (and veto) the founding branch itself."""
        state = SystemStateMatrix(entities={
            'unit_103': EntityState(entity_id='unit_103', current_dof=0.6),
        })
        avail = {'unit': {'103': {'build_city': True, 'goto_0': True}}}
        candidates = HeuristicGenerator(strategy=EXPANSIONIST).generate_candidates(
            state, avail)
        names = {c['action_name'] for c in candidates}
        assert names == {'build_city', 'goto_0'}
        founding = next(c for c in candidates if c['action_name'] == 'build_city')
        assert founding['projected_dof_delta']['unit_103'] < 0

    def test_economic_prioritizes_trade(self, sample_state):
        available = {
            'city': {'1': {'build_improvement': True}},
            'diplomacy': {'2': {'trade_agreement': True}},
        }
        gen = HeuristicGenerator(strategy=ECONOMIC)
        candidates = gen.generate_candidates(sample_state, available)
        assert len(candidates) > 0

    def test_shortlist_is_bounded(self, sample_state, sample_available):
        """The shortlist offers a few distinct branches (spec: 3-5 paths, plus
        reversible fallbacks for the veto), never a flood."""
        gen = HeuristicGenerator()
        candidates = gen.generate_candidates(sample_state, sample_available)
        assert 0 < len(candidates) <= 8

    def test_shortlist_keeps_a_reversible_fallback(self, sample_state):
        """Regression: a shortlist made only of irreversible actions froze the
        agent, because DOF-Core vetoes them all and had nothing safe to pick."""
        avail = {
            "unit": {
                # many high-gain irreversible branches...
                "102": {"build_city": True, "attack_9": True},
                # ...and one reversible alternative
                "103": {"fortify": True},
            },
        }
        state = SystemStateMatrix(entities={
            'unit_102': EntityState(entity_id='unit_102', current_dof=0.6),
            'unit_103': EntityState(entity_id='unit_103', current_dof=0.6),
        })
        candidates = HeuristicGenerator(strategy=EXPANSIONIST).generate_candidates(state, avail)
        assert any(c["is_reversible"] for c in candidates), candidates

    def test_select_best_returns_highest_dof(self, sample_state, sample_available):
        gen = HeuristicGenerator()
        candidates = gen.generate_candidates(sample_state, sample_available)
        best = gen.select_best(candidates, sample_state)
        assert best is not None
        assert 'projected_dof_delta' in best

    def test_select_best_empty_returns_none(self, sample_state):
        gen = HeuristicGenerator()
        assert gen.select_best([], sample_state) is None


# ═══════════════════════════════════════════════════════════════════════════════
# Real CivRealm vocabulary (captured from a live game)
#
# The fixture is produced by scripts/inspect_actions.py --turns 1 and holds a
# faithful slice of a real available_actions payload: real controller names
# (player/tech/unit/dipl/gov), real action names, real actor keys (int and str
# before JSON stringifies them) and both valid (truthy params) and invalid
# (empty params) actions.
# ═══════════════════════════════════════════════════════════════════════════════

import json
import pathlib

REAL_ACTIONS_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "fixtures"
    / "real_available_actions.json"
)


def _real_available() -> dict:
    assert REAL_ACTIONS_FIXTURE.exists(), (
        f"missing real action fixture: {REAL_ACTIONS_FIXTURE}. "
        "Regenerate with: .venv/bin/python scripts/inspect_actions.py --turns 1"
    )
    return json.loads(REAL_ACTIONS_FIXTURE.read_text())


class TestRealVocabularyReversibility:
    """Reversibility must be right for the names a live game actually emits."""

    @pytest.mark.parametrize("name", [
        "goto_12",
        "fortify",
        "keep_activity",
        "plant",
        "cultivate",
        "mine",
        "road",
        "set_sci_lux_tax_0_40_60",
        "change_gov_Monarchy",
        "set_tech_goal_Alphabet_2",
        "chat",
        "build_road",
    ])
    def test_reversible(self, name):
        assert classify_reversibility(name) is True

    @pytest.mark.parametrize("name", [
        "found_city",
        "research_tech_Alphabet_2",
        "build_city",
        "disband",
        "attack_15",
        "pillage",
        "declare_war_2",
    ])
    def test_not_reversible(self, name):
        assert classify_reversibility(name) is False

    def test_unknown_stays_reversible(self):
        assert classify_reversibility("some_unmapped_action_1") is True


class TestRealActionSpace:
    """generate_from_state must only offer actions the server will accept."""

    @pytest.fixture
    def state(self):
        return SystemStateMatrix(
            entities={
                'unit_102': EntityState(entity_id='unit_102', current_dof=0.6),
                'unit_104': EntityState(entity_id='unit_104', current_dof=0.6),
                'city_1': EntityState(entity_id='city_1', current_dof=0.7),
            },
        )

    def test_every_candidate_is_executable(self, state):
        avail = _real_available()
        candidates = ActionOptionGenerator().generate_from_state(state, avail)

        assert candidates, "expected candidates from a real action space"
        for cand in candidates:
            ctrl = cand["ctrl_type"]
            actor = cand["actor_id"]
            name = cand["action_name"]
            assert ctrl in avail, f"unknown controller {ctrl}"
            actors = avail[ctrl]
            assert actor in actors, f"actor {actor!r} not in {ctrl}"
            assert name in actors[actor], f"action {name!r} not offered for {ctrl}/{actor}"
            assert actors[actor][name], (
                f"candidate {ctrl}/{actor}/{name} has empty params -> the server "
                "would reject it (regression of the fortify bug)"
            )

    def test_invalid_actions_are_filtered_out(self, state):
        avail = _real_available()
        valid_pairs = {
            (ctrl, actor, name)
            for ctrl, actors in avail.items()
            for actor, actions in actors.items()
            for name, params in actions.items()
            if params
        }
        generated = {
            (c["ctrl_type"], c["actor_id"], c["action_name"])
            for c in ActionOptionGenerator().generate_from_state(state, avail)
        }
        assert generated  # non-empty
        assert generated <= valid_pairs, generated - valid_pairs

        # Sanity: the fixture really does contain invalid entries, otherwise the
        # assertion above would be vacuous.
        assert any(
            not params
            for actors in avail.values()
            for actions in actors.values()
            for params in actions.values()
        )

    def test_valid_only_false_keeps_invalid_entries(self, state):
        avail = _real_available()
        all_candidates = ActionOptionGenerator().generate_from_state(
            state, avail, valid_only=False
        )
        valid_candidates = ActionOptionGenerator().generate_from_state(
            state, avail, valid_only=True
        )
        assert len(all_candidates) > len(valid_candidates)

    def test_real_vocabulary_is_covered(self, state):
        avail = _real_available()
        ctrls = {c["ctrl_type"] for c in
                 ActionOptionGenerator().generate_from_state(state, avail)}
        # Controllers present with at least one valid action in the fixture.
        assert "unit" in ctrls
        assert "gov" in ctrls
        # tech is only reachable if its params survive the filter
        if any(params for actions in avail.get("tech", {}).values()
               for params in actions.values()):
            assert "tech" in ctrls

    def test_structured_fields_present(self, state):
        cand = ActionOptionGenerator().generate_from_state(state, _real_available())[0]
        for key in ("ctrl_type", "actor_id", "action_name", "params"):
            assert key in cand

    def test_int_actor_ids_keep_their_type(self, state):
        """civrealm emits int actor keys; a str cast breaks the env lookup."""
        avail = {"unit": {104: {"goto_0": True, "mine": {}}}}
        cands = ActionOptionGenerator().generate_from_state(state, avail)
        assert len(cands) == 1
        assert cands[0]["actor_id"] == 104
        assert isinstance(cands[0]["actor_id"], int)

    def test_string_actor_ids_are_preserved(self, state):
        avail = {"tech": {"cur_player": {"research_tech_Alphabet_2": True}}}
        cands = ActionOptionGenerator().generate_from_state(state, avail)
        assert cands[0]["actor_id"] == "cur_player"

    def test_underscore_names_survive_round_trip(self, state):
        """Actor ids and action names containing underscores must not be
        mangled: option_id is an id, the structured fields are authoritative."""
        actor = "cur_player"
        action = "research_tech_Advanced Flight_1"
        avail = {"tech": {actor: {action: True}}}
        cand = ActionOptionGenerator().generate_from_state(state, avail)[0]
        assert cand["actor_id"] == actor
        assert cand["action_name"] == action
        # option_id is lossy for parsing, but must still be a stable id
        assert cand["option_id"] == f"tech_{actor}_{action}"


class TestRealVocabularyHeuristics:
    """Strategy generation must group by ctrl_type, not by parsing option_id."""

    @pytest.fixture
    def state(self):
        from env.entity_extractor import BridgeCalibration

        return SystemStateMatrix(
            entities={
                'unit_102': EntityState(entity_id='unit_102', current_dof=0.6,
                                        dof_options=4.0),
                'city_1': EntityState(entity_id='city_1', current_dof=0.7,
                                      dof_options=8.0),
                'tech_2': EntityState(entity_id='tech_2', current_dof=0.4,
                                      dof_options=1.0),
            },
            bridge=BridgeCalibration(
                new_city_options=4.85,
                improvement_gain={'city_1': 2.33},
                unit_type_options={'Bomber': 6.54},
                improvement_options={'Temple': 1.40},
                tech_research_gain={'tech_2': 0.50},
            ),
        )

    def test_candidates_are_executable_and_capped(self, state):
        avail = _real_available()
        cands = HeuristicGenerator(strategy=DEFENSIVE).generate_candidates(state, avail)
        assert 0 < len(cands) <= 8
        for c in cands:
            assert avail[c["ctrl_type"]][c["actor_id"]][c["action_name"]]

    def test_chat_is_not_proposed(self, state):
        """The 'player' controller (chat) carries no strategic value."""
        avail = _real_available()
        cands = HeuristicGenerator().generate_candidates(state, avail)
        assert all(c["ctrl_type"] != "player" for c in cands)

    def test_defensive_prefers_fortify_over_attack_on_real_shape(self, state):
        avail = {
            "unit": {102: {"fortify": True, "attack_15": True, "goto_1": True}},
        }
        cands = HeuristicGenerator(strategy=DEFENSIVE).generate_candidates(state, avail)
        names = [c["action_name"] for c in cands]
        assert "fortify" in names and "attack_15" in names
        assert names.index("fortify") < names.index("attack_15")

    def test_expansionist_prefers_city_founding(self, state):
        """Founding is a distinct branch, priced from the state as a GAIN.

        A size-1 city outranks the settler it replaces (population is the DoF
        engine), so the founding branch is DoF-positive and must be visible to
        DOF-Core — which then weighs it against its own irreversibility penalty.
        """
        avail = {
            "unit": {102: {"found_city": True, "attack_15": True}},
        }
        cands = HeuristicGenerator(strategy=EXPANSIONIST).generate_candidates(state, avail)
        names = [c["action_name"] for c in cands]
        assert set(names) == {"found_city", "attack_15"}
        founding = next(c for c in cands if c["action_name"] == "found_city")
        assert founding["projected_dof_delta"]["unit_102"] > 0
        assert founding["is_reversible"] is False

    def test_technological_prefers_research(self, state):
        avail = {
            "tech": {"cur_player": {"research_tech_Alphabet_2": True,
                                    "chat": True}},
        }
        cands = HeuristicGenerator(strategy=TECHNOLOGICAL).generate_candidates(state, avail)
        assert cands[0]["action_name"].startswith("research_tech")

    def test_dof_gain_outranks_reversibility(self, state):
        """DoF gain is the objective; reversibility only breaks ties.

        A production order (irreversible in the bridge's classification, positive
        in DoF) must outrank a reversible advisory action with no gain.
        """
        avail = {
            "city": {1: {"produce_Bomber": True}},
            "tech": {"cur_player": {"set_tech_goal_Banking_7": True}},
        }
        cands = HeuristicGenerator(strategy=TECHNOLOGICAL).generate_candidates(state, avail)
        assert len(cands) == 2
        assert cands[0]["action_name"] == "produce_Bomber"
        assert cands[0]["projected_dof_delta"]["city_1"] > 0

    def test_measured_neutral_actions_are_not_preferred_over_gain(self, state):
        """Set a technology goal (no immediate gain) vs build something: the
        branch with a real DoF gain wins."""
        avail = {
            "tech": {"cur_player": {"set_tech_goal_Banking_7": True}},
            "city": {1: {"produce_Bomber": True}},
        }
        gen = HeuristicGenerator(strategy=TECHNOLOGICAL)
        best = gen.select_best(gen.generate_candidates(state, avail), state)
        assert best["action_name"] == "produce_Bomber"

    def test_reversible_wins_at_equal_gain(self, state):
        """Axiom 4 as a tie-break: at equal (here measured-zero) gain, prefer the
        reversible action."""
        avail = {
            "unit": {102: {"fortify": True, "fortress": True}},
        }
        cands = HeuristicGenerator(strategy=DEFENSIVE).generate_candidates(state, avail)
        gains = [sum(c["projected_dof_delta"].values()) for c in cands]
        assert all(g == pytest.approx(0.0) for g in gains)
        reversible = HeuristicGenerator(strategy=DEFENSIVE).select_best(cands, state)
        assert reversible["is_reversible"] is True

    def test_best_gain_action_survives_a_goto_flood(self, state):
        """Regression: hundreds of reversible goto_* used to fill the top-5 and
        push the best-gain action out of the shortlist. The founding branch (a
        gain in the calibrated model) must still be shortlisted, and must win
        against a flood of measured-neutral movement."""
        actions = {f"goto_{i}": True for i in range(300)}
        actions["build_city"] = True
        avail = {"unit": {102: actions}}

        cands = HeuristicGenerator(strategy=EXPANSIONIST).generate_candidates(state, avail)
        names = [c["action_name"] for c in cands]
        assert "build_city" in names, f"shortlist lost the founding branch: {names}"
        best = HeuristicGenerator(strategy=EXPANSIONIST).select_best(cands, state)
        assert best["action_name"] == "build_city"  # a real gain beats 0.0

    def test_domain_weights_keep_strategies_distinct(self, state):
        """Same raw gains, different domain weights -> different valuations."""
        gen_tech = HeuristicGenerator(strategy=TECHNOLOGICAL)
        gen_econ = HeuristicGenerator(strategy=ECONOMIC)
        research = {"ctrl_type": "tech", "projected_dof_delta": {"tech_2": 0.05},
                    "action_name": "research_tech_Alphabet_2", "is_reversible": False}
        build = {"ctrl_type": "city", "projected_dof_delta": {"city_1": 0.10},
                 "action_name": "build_unit", "is_reversible": True}
        # Weights differ per domain, so the two strategies value the same
        # candidates differently.
        assert gen_tech.weighted_dof_gain(research) != gen_econ.weighted_dof_gain(research)
        assert gen_tech.weighted_dof_gain(build) != gen_econ.weighted_dof_gain(build)


class TestRealVocabularyDofDelta:
    """DoF deltas must be produced for real controller names."""

    @pytest.fixture
    def state(self):
        from env.entity_extractor import BridgeCalibration

        return SystemStateMatrix(
            entities={
                'unit_102': EntityState(entity_id='unit_102', current_dof=0.6,
                                        dof_options=6.0),
                'city_1': EntityState(entity_id='city_1', current_dof=0.7,
                                      dof_options=8.0),
                'tech_2': EntityState(entity_id='tech_2', current_dof=0.1,
                                      dof_options=1.0),
            },
            bridge=BridgeCalibration(
                new_city_options=7.5,
                improvement_gain={'city_1': 2.0},
                tech_research_gain={'tech_2': 0.7},
            ),
        )

    def test_unit_found_city_gains_dof(self, state):
        """Founding trades the settler for a size-1 city, and the city is worth
        more (population is the DoF engine): the projection is a gain, derived
        from this state's own numbers."""
        delta = estimate_dof_delta(
            CivAction(ctrl_type='unit', actor_id=102, action_name='found_city'), state
        )
        assert delta['unit_102'] == pytest.approx(7.5 - 6.0)

    def test_unit_attack_has_no_invented_delta(self, state):
        """An attack's DoF effect is unmeasured; its modelled cost is that it is
        irreversible."""
        delta = estimate_dof_delta(
            CivAction(ctrl_type='unit', actor_id=102, action_name='attack_15'), state
        )
        assert delta == {}
        assert classify_reversibility('attack_15') is False

    def test_gov_actions_are_measured_neutral(self, state):
        """Tax and government changes were guessed at +0.01/+0.02 per city;
        measured on a live game they leave the index unchanged (0.0000)."""
        for name in ('set_sci_lux_tax_0_40_60', 'change_gov_Anarchy'):
            delta = estimate_dof_delta(
                CivAction(ctrl_type='gov', actor_id=0, action_name=name), state
            )
            assert sum(delta.values()) == pytest.approx(0.0), name

    def test_dipl_treaty_is_measured_neutral(self, state):
        delta = estimate_dof_delta(
            CivAction(ctrl_type='dipl', actor_id=2, action_name='accept_treaty_2'), state
        )
        assert sum(delta.values()) == pytest.approx(0.0)

    def test_tech_and_player_have_no_entity_delta(self, state):
        """Choosing a research goal is advisory (the doc's §5.1: it changes the
        plan, not the immediate option space), and `chat` carries nothing at all —
        the player controller has no entity to attribute a change to."""
        goal = estimate_dof_delta(
            CivAction(ctrl_type='tech', actor_id='cur_player',
                      action_name='set_tech_goal_Alphabet_2'), state)
        assert set(goal.values()) == {0.0}
        assert estimate_dof_delta(
            CivAction(ctrl_type='player', actor_id='message', action_name='chat'),
            state) == {}

    def test_research_is_priced_from_what_it_unlocks(self, state):
        """Research used to be a 0.0000 action (and before that a +0.05 guess).
        With the gate model it is priced from the technology's own unlocked set,
        per turn, attributed to that technology's entity."""
        delta = estimate_dof_delta(
            CivAction(ctrl_type='tech', actor_id='cur_player',
                      action_name='research_tech_Alphabet_2'), state
        )
        assert delta['tech_2'] == pytest.approx(0.7)

    def test_research_for_unknown_tech_id_is_ignored(self, state):
        delta = estimate_dof_delta(
            CivAction(ctrl_type='tech', actor_id='cur_player',
                      action_name='research_tech_Alphabet_999'), state
        )
        assert sum(delta.values()) == pytest.approx(0.0)
