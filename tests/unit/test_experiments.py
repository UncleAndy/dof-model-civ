"""Эксперименты и незнание: витрина вопросов + цена снятия неопределённости.

Проверяем три вещи, которых раньше не было:
  * **витрина** — модель показывает, чего она не знает (`unknowns`), и с чем мир
    спорит (`contested`), вместо молчаливого нуля;
  * **мотив** — действие с неизмеренным эффектом получает надбавку, и она убывает
    по мере проб; измеренный ноль надбавки не получает (это знание, а не незнание);
  * **принцип** — эксперимент нельзя оплачивать необратимым действием.
"""
from __future__ import annotations

import pytest

from env import config as cfg
from env.action_mapper import CivAction, classify_reversibility, estimate_dof_delta
from env.entity_extractor import BridgeCalibration, EntityState, SystemStateMatrix
from env.experiments import (
    PROBE_MAP,
    action_known,
    exploration_budget,
    experiment_families,
    family_of,
    note_choice,
    probe_bonus,
    questions,
    uncertainty_bonus,
)
from env.world_model import CONFIDENCE_K, Provenance, WorldModel


def a_state(*, model_values=None, attempts=None, contested=None,
            confidence_by_key=None):
    bridge = BridgeCalibration(
        model_values=model_values if model_values is not None
        else {"AXIOM4_PENALTY_OPTIONS": cfg.AXIOM4_PENALTY_OPTIONS},
        experiment_attempts=attempts or {},
        contested_keys=contested or [],
        confidence_by_key=confidence_by_key or {},
    )
    return SystemStateMatrix(
        entities={"city_1": EntityState(entity_id="city_1", entity_type="city",
                                        dof_count=8.0, current_dof=0.8)},
        bridge=bridge,
    )


class TestVisibleIgnorance:
    def test_unknowns_lists_never_confirmed_keys(self):
        model = WorldModel()
        unknown = {item["key"] for item in model.unknowns()}
        assert unknown                       # модель что-то предполагает
        assert all(model.corroborations.get(k, 0) == 0 for k in unknown)

    def test_a_confirmed_key_leaves_the_unknown_list(self):
        model = WorldModel()
        key = "CITY_POP"
        assert key in {item["key"] for item in model.unknowns()}
        model.observe(key, model.get(key), turn=1, source=Provenance.MEASURED)
        assert key not in {item["key"] for item in model.unknowns()}

    def test_confidence_grows_with_confirmation_and_halves_at_k(self):
        model = WorldModel()
        key = "CITY_POP"
        assert model.confidence(key) == 0.0
        for turn in range(1, CONFIDENCE_K + 1):
            model.observe(key, model.get(key), turn=turn, source=Provenance.MEASURED)
        assert model.confidence(key) == pytest.approx(0.5)
        model.observe(key, model.get(key), turn=99, source=Provenance.MEASURED)
        assert model.confidence(key) > 0.5


class TestContestedKeys:
    def _key(self):
        return "CITY_BASE"

    def test_a_key_the_world_keeps_arguing_about_becomes_a_task(self):
        model = WorldModel()
        key = self._key()
        prior = model.get(key)
        for turn in range(3):
            model.observe(key, prior + 1.0, turn=turn, source=Provenance.ASSUMED)
        assert model.pending_count(key) == 3
        contested = model.contested(min_reports=3)
        assert [item["key"] for item in contested] == [key]
        assert contested[0]["reports"] == 3
        assert contested[0]["value"] == prior        # модель всё ещё держит своё
        assert contested[0]["observed"]              # но помнит, что мир говорит иначе

    def test_one_disagreement_is_not_a_task(self):
        model = WorldModel()
        model.observe(self._key(), 123.0, turn=1, source=Provenance.ASSUMED)
        assert model.contested(min_reports=3) == []


class TestExperimentCounter:
    def test_attempts_raise_confidence_and_are_journalled(self):
        model = WorldModel()
        assert model.experiment_confidence("dipl") == 0.0
        for turn in range(1, CONFIDENCE_K + 1):
            model.record_experiment("dipl", turn=turn)
        assert model.experiment_attempts["dipl"] == CONFIDENCE_K
        assert model.experiment_confidence("dipl") == pytest.approx(0.5)
        assert any(r.key == "experiment.dipl" for r in model.reconciliations)


class TestUncertaintyBonus:
    VALS = {"AXIOM4_PENALTY_OPTIONS": cfg.AXIOM4_PENALTY_OPTIONS}

    def test_measured_zero_earns_nothing(self):
        # Дорога измерена как ноль: это знание, а не незнание.
        assert action_known("unit", "road") is True
        assert uncertainty_bonus("unit", "road", self.VALS, 0.0) == 0.0

    def test_a_work_whose_extra_was_measured_counts_as_known(self):
        # `build_road` ставит экстру Road, а эффект Road определён ПРАВИЛАМИ
        # (`road.trade_incr=1` × `road_trade_incr_pct`) — значит работа известна,
        # и платить за её «эксперимент» нечего. Прежняя посылка «замерен нулём
        # `map.output`» отозвана: нули того датчика улучшений не измеряли.
        assert action_known("unit", "build_road") is True
        assert action_known("unit", "irrigation") is True
        # `mine` известна из таблицы ΔDoF (измеренный ноль) — тоже знание.
        assert action_known("unit", "mine") is True
        # А вот действие, которого нет ни в одной таблице, — настоящий эксперимент.
        assert action_known("unit", "hut_enter_6") is False

    def test_terrain_work_knowledge_comes_from_rules_not_blind_zero(self):
        # Знание о работах обязано идти из ПРАВИЛ, а не из отозванного слепого нуля.
        # Если бы оно держалось на нуле датчика, отзыв нуля молча сделал бы работу
        # «неизвестной», и агент платил бы за её «эксперимент» в каждом матче.
        assert "Road" not in cfg.MEASURED_EXTRA_EFFECTS
        assert "Irrigation" not in cfg.MEASURED_EXTRA_EFFECTS
        assert cfg.MEASURED_EXTRA_EFFECTS.get("Coal") == (0.0, 2.0, 0.0)
        from env.terrain_work_effects import effect_known_from_rules
        assert effect_known_from_rules("Road") is True
        assert effect_known_from_rules("Irrigation") is True
        assert effect_known_from_rules("Mine") is True
        # Экстра, которой нет в правилах, знанием не объявляется.
        assert effect_known_from_rules("Farmland") is False

    def test_note_choice_counts_only_real_experiments(self):
        model = WorldModel()
        assert note_choice(model, "unit", "build_road", turn=1) is False
        assert model.experiment_attempts == {}
        assert note_choice(model, "unit", "hut_enter_6", turn=1) is True
        assert model.experiment_attempts == {"hut_enter": 1}

    def test_unknown_reversible_action_earns_the_full_budget(self):
        assert action_known("city", "buy_improvement") is False
        assert uncertainty_bonus("city", "buy_improvement", self.VALS, 0.0) == \
            pytest.approx(cfg.AXIOM4_PENALTY_OPTIONS)

    def test_bonus_decays_as_the_family_is_tried(self):
        seen = []
        for attempts in (0, 1, 3, 10):
            seen.append(uncertainty_bonus("city", "buy_improvement", self.VALS,
                                          attempts))
        assert seen == sorted(seen, reverse=True)
        assert seen[0] == pytest.approx(cfg.AXIOM4_PENALTY_OPTIONS)
        assert seen[-1] < seen[0]

    def test_curiosity_is_bounded_and_then_stops(self):
        # Любопытство ограничено: после CONFIDENCE_K проб семейства надбавка
        # обнуляется, иначе оно вытеснило бы полезные действия навсегда.
        assert uncertainty_bonus("city", "buy_improvement", self.VALS, 0) > 0
        assert uncertainty_bonus("city", "buy_improvement", self.VALS,
                                 CONFIDENCE_K) == 0.0
        assert uncertainty_bonus("city", "buy_improvement", self.VALS, 99) == 0.0
        assert exploration_budget(0) == 1.0
        assert exploration_budget(CONFIDENCE_K) == 0.0

    def test_family_strips_parameters_so_probes_share_a_counter(self):
        assert family_of("set_sci_lux_tax_0_40_60") == "set_sci_lux_tax"
        assert family_of("goto_120") == "goto"
        # Живые имена с координатами: весь числовой хвост снимается, иначе каждое
        # место работы считалось бы новым семейством и бюджет не исчерпывался.
        assert family_of("city_work_13_-2_-1") == "city_work"
        assert family_of("city_unwork_9_-2_0") == "city_unwork"
        assert family_of("research_tech_Advanced Flight_2") == \
            "research_tech_Advanced Flight"
        assert family_of("buy_improvement") == "buy_improvement"
        assert family_of("") == ""

    def test_experiment_families_lists_only_unmeasured_candidates(self):
        candidates = [
            {"ctrl_type": "unit", "action_name": "goto_3"},        # измерено
            {"ctrl_type": "city", "action_name": "buy_improvement"},  # не измерено
            {"ctrl_type": "city", "action_name": "buy_improvement"},
        ]
        assert experiment_families(candidates) == [("city", "buy_improvement")]


class TestProbeBonus:
    VALS = {"AXIOM4_PENALTY_OPTIONS": cfg.AXIOM4_PENALTY_OPTIONS}

    def test_founding_pays_for_settling_a_contested_city_value(self):
        contested = [{"key": "new_city_options", "reports": 4}]
        bonus = probe_bonus("unit", "build_city", contested, lambda key: 0.0, self.VALS)
        assert bonus == pytest.approx(cfg.AXIOM4_PENALTY_OPTIONS)
        assert "new_city_options" in PROBE_MAP["build_city"]

    def test_no_contested_key_no_probe_bonus(self):
        assert probe_bonus("unit", "build_city", [], lambda key: 0.0, self.VALS) == 0.0

    def test_unrelated_action_does_not_probe(self):
        contested = [{"key": "new_city_options", "reports": 4}]
        assert probe_bonus("unit", "goto_3", contested, lambda key: 0.0, self.VALS) == 0.0


class TestMapperPaysForExperiments:
    def test_unknown_reversible_action_carries_the_bonus(self):
        action = CivAction(ctrl_type="city", actor_id=1, action_name="buy_improvement")
        delta = estimate_dof_delta(action, a_state())
        assert delta == {"city_1": pytest.approx(cfg.AXIOM4_PENALTY_OPTIONS)}

    def test_measured_zero_action_keeps_its_zero(self):
        state = a_state()
        state.entities["unit_7"] = EntityState(entity_id="unit_7", entity_type="unit",
                                              dof_count=1.0, current_dof=0.1)
        action = CivAction(ctrl_type="unit", actor_id=7, action_name="road")
        assert estimate_dof_delta(action, state).get("unit_7", 0.0) == 0.0

    def test_irreversible_probe_is_not_paid(self):
        # Платить за знание необратимым действием — тратить опции без возврата.
        state = a_state()
        state.entities["unit_7"] = EntityState(entity_id="unit_7", entity_type="unit",
                                              dof_count=1.0, current_dof=0.1)
        action = CivAction(ctrl_type="unit", actor_id=7, action_name="attack")
        assert classify_reversibility("attack") is False
        assert estimate_dof_delta(action, state) == {}

    def test_bonus_shrinks_once_the_family_has_been_tried(self):
        action = CivAction(ctrl_type="city", actor_id=1, action_name="buy_improvement")
        fresh = estimate_dof_delta(action, a_state())["city_1"]
        tried = estimate_dof_delta(
            action, a_state(attempts={"buy_improvement": 1}))["city_1"]
        assert tried < fresh

    def test_a_family_that_has_been_probed_enough_is_not_paid(self):
        action = CivAction(ctrl_type="city", actor_id=1, action_name="buy_improvement")
        state = a_state(attempts={"buy_improvement": CONFIDENCE_K})
        assert estimate_dof_delta(action, state).get("city_1", 0.0) == 0.0


class TestQuestionsPanel:
    def test_founding_pays_the_probe_bonus_where_evidence_is_produced(self, monkeypatch):
        # This test exercises projection math, not persistent runtime wedge evidence.
        monkeypatch.setattr("env.action_mapper.is_wedged", lambda *_, **__: False)
        # Ветка основания выходит из estimate_dof_delta РАНЬШЕ общей обработки
        # неизмеренного, поэтому надбавка за зонд обязана платиться прямо здесь —
        # иначе она недостижима ровно там, где рождается свидетельство.
        state = SystemStateMatrix(
            entities={"unit_9": EntityState(entity_id="unit_9", entity_type="unit",
                                            dof_count=4.0, current_dof=0.4)},
            bridge=BridgeCalibration(
                new_city_options=3.0,
                new_city_options_by_unit={"unit_9": 9.0},
                model_values={"AXIOM4_PENALTY_OPTIONS": cfg.AXIOM4_PENALTY_OPTIONS},
                contested_keys=[{"key": "new_city_options", "reports": 4}],
                confidence_by_key={"new_city_options": 0.0},
            ),
        )
        action = CivAction(ctrl_type="unit", actor_id=9, action_name="build_city")
        delta = estimate_dof_delta(action, state)
        assert delta["unit_9"] == pytest.approx(5.0 + cfg.AXIOM4_PENALTY_OPTIONS)

    def test_panel_reports_unknowns_contested_and_attempts(self):
        model = WorldModel()
        model.record_experiment("dipl", turn=1)
        panel = questions(model)
        assert panel["unknown_keys"] and panel["confidence_k"] == CONFIDENCE_K
        assert panel["experiment_attempts"] == {"dipl": 1}
        assert "contested_keys" in panel


def _rich_obs(*, with_city: bool):
    """Наблюдение с годной площадкой: без города и с только что основанным."""
    import numpy as np

    from env.entity_extractor import GameStateExtractor

    out = np.zeros((14, 14, 6), dtype=float)
    out[:, :, 0] = 3.0                      # еда 3 на клетке: площадка годна
    obs = {
        "map": {"output": out},
        "city": {},
        "unit": {"7": {"rule_name": "Settlers", "x": 6, "y": 6,
                       "type_hp": 20, "health": 20, "type_move_rate": 1}},
    }
    if with_city:
        obs["city"] = {"121": {"id": "121", "owner": 0, "x": 6, "y": 6, "size": 1,
                               "surplus_food": 3, "surplus_shield": 0,
                               "surplus_trade": 0, "food_stock": 0,
                               "granary_size": 20, "improvements": [],
                               "city_corruption": 0}}
    return obs, GameStateExtractor


class TestCityPredictionMeetsTheFact:
    """D: прогноз нового города уходит в статистику, когда мир его подтверждает."""

    def test_a_pair_is_recorded_when_a_city_appears(self):
        obs, extractor_cls = _rich_obs(with_city=False)
        ex = extractor_cls(my_player_id=0)
        ex.extract(obs, {}, 1)
        assert ex._city_predictions and max(ex._city_predictions.values()) > 0
        assert ex._carrier_pos == {"unit_7": (6, 6)}   # площадку знаем чью

        obs_with_city, _ = _rich_obs(with_city=True)
        ex.extract(obs_with_city, {}, 2)
        pairs = ex.model.pairs.get("new_city_options")
        assert pairs and len(pairs) == 1
        turn, predicted, observed = pairs[0]
        assert turn == 2 and predicted > 0 and observed > 0
        # Прогноз не «сгорает»: на этом же ходу он пересчитывается для СЛЕДУЮЩЕГО
        # города (носитель ещё жив), поэтому здесь он снова заполнен.
        assert ex._city_predictions

    def test_no_pair_without_a_new_city(self):
        obs, extractor_cls = _rich_obs(with_city=False)
        ex = extractor_cls(my_player_id=0)
        ex.extract(obs, {}, 1)
        ex.extract(obs, {}, 2)
        assert ex.model.pairs.get("new_city_options") is None
