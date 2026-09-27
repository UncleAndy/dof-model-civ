"""Склад измеренных фактов: согласие обязательно, противоречие = «не знаем».

Зачем эти тесты. Стоимость и опции типа производства нельзя вывести из наблюдения —
их надо замерить (или подсмотреть у живого юнита) и сохранить. Соблазн ровно один:
если замеры разошлись, взять среднее. Это подгонка: оба числа — константы мира, и
расхождение означает «мы ещё не знаем», а не «истина посередине».
"""
from __future__ import annotations

from env.measured_facts import MeasuredFacts


class TestCosts:
    def test_a_measured_cost_is_returned(self, tmp_path):
        facts = MeasuredFacts(tmp_path / "facts.json")
        facts.observe_cost("Settlers", 40.0, kind="unit", source="probe")
        assert facts.cost("Settlers") == 40.0
        assert facts.agreement("Settlers") == 1.0

    def test_an_unmeasured_type_is_unknown_not_zero(self, tmp_path):
        facts = MeasuredFacts(tmp_path / "facts.json")
        assert facts.cost("Knights") is None      # не 0.0!
        assert facts.options("Knights") is None
        assert facts.known() == []

    def test_disagreeing_measurements_mean_unknown(self, tmp_path):
        """Половина замеров за 30, половина за 40 — это не «35»."""
        facts = MeasuredFacts(tmp_path / "facts.json")
        facts.observe_cost("Knights", 30.0)
        facts.observe_cost("Knights", 40.0)
        assert facts.cost("Knights") is None
        assert facts.agreement("Knights") == 0.0

    def test_repeated_agreement_keeps_the_value(self, tmp_path):
        facts = MeasuredFacts(tmp_path / "facts.json")
        for _ in range(3):
            facts.observe_cost("Warriors", 10.0)
        facts.observe_cost("Warriors", 12.0)      # одинокое расхождение
        assert facts.cost("Warriors") == 10.0
        assert facts.agreement("Warriors") == 0.75

    def test_facts_survive_the_run(self, tmp_path):
        path = tmp_path / "facts.json"
        first = MeasuredFacts(path)
        first.observe_cost("Workers", 10.0, turn=7)
        first.save()

        second = MeasuredFacts(path)
        assert second.cost("Workers") == 10.0
        assert second.facts["Workers"]["n"] == 1
        assert second.facts["Workers"]["last_turn"] == 7

    def test_a_nonpositive_or_missing_cost_is_not_a_fact(self, tmp_path):
        facts = MeasuredFacts(tmp_path / "facts.json")
        facts.observe_cost("Settlers", None)
        facts.observe_cost("Settlers", 0.0)
        facts.observe_cost("Settlers", -5.0)
        assert facts.facts == {}


class TestTypeOptions:
    """Опции типа учатся из живых юнитов — их надо сохранить на будущее."""

    def test_options_are_learned_and_kept(self, tmp_path):
        facts = MeasuredFacts(tmp_path / "facts.json")
        facts.observe_type("Settlers", cost=40.0, options=3.8125,
                           source="observed", turn=1)
        assert facts.options("Settlers") == 3.8125
        assert facts.cost("Settlers") == 40.0

    def test_the_pair_survives_after_the_unit_is_gone(self, tmp_path):
        """Ровно тот случай, ради которого склад и нужен: носитель основал город."""
        path = tmp_path / "facts.json"
        learned = MeasuredFacts(path)
        learned.observe_type("Settlers", cost=40.0, options=3.8125)
        learned.save()

        after = MeasuredFacts(path)
        assert after.cost("Settlers") == 40.0
        assert after.options("Settlers") == 3.8125

    def test_a_cost_without_options_is_still_useful(self, tmp_path):
        facts = MeasuredFacts(tmp_path / "facts.json")
        facts.observe_cost("Knights", 30.0)
        assert facts.cost("Knights") == 30.0
        assert facts.options("Knights") is None

    def test_options_may_disagree_and_then_they_are_unknown(self, tmp_path):
        facts = MeasuredFacts(tmp_path / "facts.json")
        facts.observe_type("Settlers", options=3.0)
        facts.observe_type("Settlers", options=5.0)
        assert facts.options("Settlers") is None

    def test_observations_are_bounded(self, tmp_path):
        """Склад пополняется каждый ход — без границы он превратился бы в лог."""
        from env.measured_facts import MAX_OBSERVATIONS

        facts = MeasuredFacts(tmp_path / "facts.json")
        for _ in range(MAX_OBSERVATIONS + 20):
            facts.observe_type("Workers", options=4.5)
        assert len(facts.facts["Workers"]["options"]) == MAX_OBSERVATIONS
        assert facts.options("Workers") == 4.5

    def test_summary_names_both_numbers(self, tmp_path):
        facts = MeasuredFacts(tmp_path / "facts.json")
        facts.observe_type("Granary", cost=60.0, options=2.0, kind="improvement")
        summary = facts.summary()
        assert summary["Granary"]["cost"] == 60.0
        assert summary["Granary"]["options"] == 2.0
        assert summary["Granary"]["kind"] == "improvement"

    def test_the_older_file_shape_is_still_read(self, tmp_path):
        """Совместимость: первая редакция склада писала ключ `costs`."""
        path = tmp_path / "facts.json"
        path.write_text('{"costs": {"Settlers": {"kind": "unit", '
                        '"observations": [40.0]}}}', encoding="utf-8")
        facts = MeasuredFacts(path)
        assert facts.cost("Settlers") == 40.0


class TestCostFromCity:
    """Стоимость из записи города — то, чем замер в бою и заканчивается."""

    def test_the_measured_examples(self):
        from env.measured_facts import cost_from_city

        # Живые наблюдения: Settlers stock=3 proc=0.075 → 40; Warriors 6/0.6 → 10;
        # Workers 9/0.9 → 10; тот же поселенец при пяти щитах 5/0.125 → 40.
        assert cost_from_city({"shield_stock": 3, "prod_process": 0.075}) == 40.0
        assert cost_from_city({"shield_stock": 6, "prod_process": 0.6}) == 10.0
        assert cost_from_city({"shield_stock": 9, "prod_process": 0.9}) == 10.0
        assert cost_from_city({"shield_stock": 5, "prod_process": 0.125}) == 40.0

    def test_missing_or_zero_fields_are_not_a_measurement(self):
        from env.measured_facts import cost_from_city

        assert cost_from_city({}) is None
        assert cost_from_city({"shield_stock": 0, "prod_process": 0.5}) is None
        assert cost_from_city({"shield_stock": 5, "prod_process": 0}) is None
        assert cost_from_city({"shield_stock": None, "prod_process": 0.5}) is None

    def test_a_probe_result_lands_in_the_store(self, tmp_path):
        """Полный круг: прочитали у мира, записали, переживает перезапуск."""
        from env.measured_facts import cost_from_city

        path = tmp_path / "facts.json"
        facts = MeasuredFacts(path)
        facts.observe_type("Warriors", cost=cost_from_city(
            {"shield_stock": 6, "prod_process": 0.6}), source="probe-in-agent")
        facts.save()

        again = MeasuredFacts(path)
        assert again.cost("Warriors") == 10.0
        assert again.facts["Warriors"]["source"] == "probe-in-agent"
