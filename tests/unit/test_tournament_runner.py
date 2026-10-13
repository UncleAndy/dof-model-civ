"""
Tests for the tournament runner's pure helpers.

Only the server-independent pieces are exercised: importing the module must not
require a running Freeciv-web (``Ports`` is imported lazily inside
``allocate_port``), which is what makes these tests safe in CI.
"""
import importlib.util
import pathlib
import sys

import pytest

RUNNER_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "baselines"
    / "run_real_tournament.py"
)


@pytest.fixture(scope="module")
def runner():
    # The runner imports civrealm/gymnasium at module level; skip cleanly when
    # they are not installed instead of erroring out.
    pytest.importorskip("civrealm")
    pytest.importorskip("gymnasium")

    argv_before = list(sys.argv)
    spec = importlib.util.spec_from_file_location("dof_runner", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.argv = argv_before
    return module


class TestToAction:
    def test_uses_structured_fields(self, runner):
        candidate = {
            "option_id": "unit_102_found_city",
            "ctrl_type": "unit",
            "actor_id": 102,
            "action_name": "found_city",
        }
        assert runner._to_action(candidate) == ("unit", 102, "found_city")

    def test_keeps_int_actor_type(self, runner):
        action = runner._to_action(
            {"ctrl_type": "unit", "actor_id": 104, "action_name": "goto_0"}
        )
        assert isinstance(action[1], int)

    def test_keeps_str_actor_type(self, runner):
        action = runner._to_action(
            {"ctrl_type": "tech", "actor_id": "cur_player",
             "action_name": "research_tech_Advanced Flight_1"}
        )
        assert action == ("tech", "cur_player", "research_tech_Advanced Flight_1")

    def test_missing_fields_return_none(self, runner):
        assert runner._to_action({"option_id": "unit_1_x"}) is None
        assert runner._to_action({}) is None


class TestBuildAgent:
    def test_random_and_noop(self, runner):
        from civrealm.agents import RandomAgent

        assert isinstance(runner.build_agent("random", None), RandomAgent)
        assert isinstance(runner.build_agent("no-op", None), runner.NoOpAgent)

    def test_dof_agent_is_created_for_each_strategy(self, runner):
        from brain.generator.heuristics import ALL_STRATEGIES

        for strategy in ALL_STRATEGIES:
            agent = runner.build_agent(f"dof_{strategy.name}", None)
            assert hasattr(agent, "act")

    def test_unknown_agent_falls_back_to_random(self, runner):
        from civrealm.agents import RandomAgent

        assert isinstance(runner.build_agent("mystery", None), RandomAgent)


class TestAgentSelection:
    def test_all_agents_available(self, runner):
        class Args:
            only = ""

        agents = runner._resolve_agent_types(Args())
        assert "random" in agents and "no-op" in agents
        assert "dof_defensive" in agents
        assert len(agents) == 7

    def test_subset_is_respected(self, runner):
        class Args:
            only = "random, dof_economic"

        assert runner._resolve_agent_types(Args()) == ["random", "dof_economic"]

    def test_unknown_subset_exits(self, runner):
        class Args:
            only = "bogus"

        with pytest.raises(SystemExit) as exc:
            runner._resolve_agent_types(Args())
        assert exc.value.code == 2


class TestCoreWiring:
    """The tournament must exercise the Rust DOF-Core, not a Python lookalike."""

    def test_core_availability_flag_is_exposed(self, runner):
        assert isinstance(runner.HAVE_DOF_CORE, bool)

    def test_core_conversions(self, runner):
        pytest.importorskip("dof_core")
        from env.entity_extractor import EntityState, SystemStateMatrix

        state = SystemStateMatrix(entities={
            'unit_1': EntityState(entity_id='unit_1', current_dof=0.5),
        })
        entities = runner._core_entities(state)
        assert len(entities) == 1
        assert entities[0].entity_id == 'unit_1'

        candidates = [{
            "option_id": "unit_1_build_city",
            "description": "unit: 1 build_city",
            "projected_dof_delta": {"unit_1": 0.3},
            "is_reversible": False,
        }]
        actions = runner._core_actions(candidates)
        assert actions[0].action_id == "unit_1_build_city"
        assert actions[0].is_reversible is False
        # Deltas are projected in options; the core works in the DOF-SPEC [0, 1]
        # range, so the bridge converts them with the same shared reference it
        # uses for the entities themselves.
        from env.config import CORE_DOF_SCALE

        assert list(actions[0].dof_delta) == [("unit_1", 0.3 / CORE_DOF_SCALE)]

    def test_core_rejects_irreversible_low_gain_and_skips_when_all_negative(self, runner):
        """DOF-Core: irreversible actions pay a context-switch penalty, and when
        every option has a negative net delta the correct choice is to not act."""
        pytest.importorskip("dof_core")
        core = runner.DOFCalculusCore()

        entities = [runner.CoreEntity(entity_id="unit_1", current_dof=0.5)]
        # +0.05 gain but irreversible -> 0.05 - 0.5 penalty < 0 -> no action
        actions = [runner.CoreAction(
            action_id="unit_1_build_city", description="", dof_delta=[("unit_1", 0.05)],
            is_reversible=False, duration_turns=1.0,
        )]
        decision = core.select_best(entities, actions)
        assert decision.chosen_action_id is None


class TestTurnPhase:
    """CivRealm only advances the turn when the action handed to env.step is None.

    An agent that always finds something to do therefore plays the whole match
    inside turn 1 and the AI opponents never move — the artefact that made a
    no-op baseline look like the strongest strategy.
    """

    def test_none_ends_the_turn(self, runner):
        assert runner._turn_phase(None, set(), 0, 20) == ("end_turn", None)

    def test_first_decision_acts(self, runner):
        assert runner._turn_phase(("unit", 5, "fortify"), set(), 0, 20) == \
            ("act", ("unit", 5))

    def test_repeat_actor_in_same_turn_ends_the_turn(self, runner):
        """One decision per actor per turn: without this a reversible action with
        a positive-looking projection is repeated forever (`change_gov_*`)."""
        used = {("gov", 0)}
        assert runner._turn_phase(("gov", 0, "change_gov_Despotism"), used, 1, 20) == \
            ("end_turn", None)

    def test_decision_cap_ends_the_turn(self, runner):
        assert runner._turn_phase(("unit", 9, "goto_0"), set(), 20, 20) == \
            ("end_turn", None)

    def test_different_actors_act(self, runner):
        assert runner._turn_phase(("unit", 6, "fortify"), {("unit", 5)}, 1, 20) == \
            ("act", ("unit", 6))


class TestLookaheadWiring:
    """The long-game variant deepens DOF-Core's lookahead; the wiring must carry
    the horizon, the penalty and the candidate cap through build_agent."""

    def test_core_horizon_and_penalty_are_configurable(self, runner):
        pytest.importorskip("dof_core")
        core = runner.DOFCalculusCore(lookahead_horizon=5,
                                      context_switch_penalty=0.25)
        assert core.lookahead_horizon == 5
        assert core.context_switch_penalty == pytest.approx(0.25)

    def test_build_agent_applies_candidate_cap(self, runner, extractor=None):
        from env.entity_extractor import GameStateExtractor

        agent = runner.build_agent("dof_defensive", GameStateExtractor(my_player_id=0),
                                   lookahead=5, context_switch_penalty=0.3,
                                   max_candidates=4)
        assert agent is not None  # construction must not require a live game

    def test_generator_respects_max_candidates(self):
        from brain.generator.heuristics import DEFENSIVE, HeuristicGenerator
        from env.entity_extractor import EntityState, SystemStateMatrix

        state = SystemStateMatrix(entities={
            'unit_102': EntityState(entity_id='unit_102', current_dof=0.6),
        })
        avail = {"unit": {102: {f"actiontype{i}": True for i in range(12)}}}
        gen = HeuristicGenerator(strategy=DEFENSIVE, max_candidates=3)
        assert len(gen.generate_candidates(state, avail)) <= 3

    def test_parser_exposes_the_new_flags(self, runner):
        args = runner._parse_cli(
            ["--lookahead", "7", "--context-switch-penalty", "0.25",
             "--max-candidates", "5"])
        assert args.lookahead == 7
        assert args.context_switch_penalty == pytest.approx(0.25)
        assert args.max_candidates == 5


class TestSlotRange:
    def test_guard_covers_multiplayer_pool(self, runner):
        """The published-port range (6000-6009) is not the slot range: the
        auto-allocated multiplayer pool is 6300-6331."""
        assert runner.MIN_PORT == 6000
        assert runner.MAX_PORT == 6331

    def test_match_result_alias_kept(self, runner):
        """Older scripts imported MatchResult; keep the alias working."""
        from metrics.tracker import MatchMetrics

        assert runner.MatchResult is MatchMetrics


class TestWedgeContext:
    def test_action_context_accepts_canonical_entity_ids(self, runner):
        observations = (
            (("unit", "unit_7", "build_city"), {"7": {"x": 4, "y": 5}}),
            (("unit", 7, "build_city"), {"unit_7": {"x": 4, "y": 5}}),
            (("unit", "unit_7", "build_city"), {"unit_7": {"x": 4, "y": 5}}),
        )
        for action, units in observations:
            assert runner._action_position_context(action, {"unit": units}) == {
                "position": [4, 5]}

    def test_timeout_and_returned_step_are_position_scoped(
            self, runner, tmp_path, monkeypatch):
        from types import SimpleNamespace
        import json
        from env import wedged

        path = tmp_path / "wedged.json"
        monkeypatch.setattr(wedged, "WEDGED_FILE", path)
        wedged.reset_cache()
        metrics = SimpleNamespace(agent_name="dof_expansionist", wedge_action=None)
        action = ("unit", 7, "build_city")
        obs = {"unit": {"7": {"x": 4, "y": 5, "type_rule_name": "Settlers"}}}
        context = {"position": (4, 5)}
        try:
            action_context = runner._action_position_context(action, obs)
            runner._record_wedge(metrics, action, 1, action_context)
            runner._record_wedge(metrics, action, 2, action_context)
            assert wedged.is_wedged("unit", "build_city", context=context)

            # Founding consumes the unit, so the post-step observation lacks its ID.
            assert runner._action_position_context(action, {"unit": {}}) == {}
            runner._record_step_success(metrics, action, 3, action_context)
            assert not wedged.is_wedged("unit", "build_city", context=context)
            entry = json.loads(path.read_text())["unit/build_city"]
            assert entry["seen"] == 2
            assert entry["scopes"]["position:4,5"]["successes"] == 1
        finally:
            wedged.reset_cache()