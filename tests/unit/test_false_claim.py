"""Заведомо неверное утверждение должно быть исправлено миром.

Проверяем ровно ту ветку, которую живой мир сам почти не вызывает: он
**дополняет** модель (новые факты), а не спорит с ней. Поэтому вопрос «а если
модель ошибается — реальность её поправит?» до сих пор был верой, а не фактом.
Здесь он проверяется на уровне модели; тот же путь запускается на живом стенде
флагом `--false-claim`.
"""
from __future__ import annotations

from env.world_model import Provenance, WorldModel


class TestFalseClaimIsCorrected:
    def test_the_world_corrects_a_maximally_trusted_false_claim(self):
        model = WorldModel()
        model.plant_false_claim('rules.citymindist', 3.0, note="тест")
        assert model.get('rules.citymindist') == 3.0

        rec = model.observe('rules.citymindist', 2.0, turn=1,
                            source=Provenance.RULESET, evidence="obs['rules']")

        assert rec.verdict == 'corrected'
        assert rec.prior == 3.0 and rec.observed == 2.0
        assert model.get('rules.citymindist') == 2.0
        assert 'rules.citymindist' in [e.key for e in model.corrections()]

    def test_the_old_value_stays_in_history(self):
        model = WorldModel()
        model.plant_false_claim('rules.citymindist', 3.0)
        model.observe('rules.citymindist', 2.0, turn=1, source=Provenance.RULESET)
        history = model.entries['rules.citymindist'].history
        assert history and history[-1]['old'] == 3.0 and history[-1]['new'] == 2.0

    def test_a_false_claim_is_marked_as_such_not_as_a_measurement(self):
        model = WorldModel()
        model.plant_false_claim('rules.food_cost', 4.0, note="проверка")
        entry = model.entries['rules.food_cost']
        assert 'ЗАВЕДОМО НЕВЕРНОЕ' in entry.evidence
        assert 'проверка' in entry.evidence

    def test_a_weaker_report_cannot_correct_a_stronger_entry(self):
        # Обратная сторона: исправление не должно быть всеядным. Если мир
        # сообщает факт слабее (предположение против ruleset), это улика, а не
        # правка — иначе «реальность первична» превратилась бы во «что угодно
        # первично».
        model = WorldModel()
        model.observe('rules.citymindist', 2.0, turn=1, source=Provenance.RULESET)
        rec = model.observe('rules.citymindist', 3.0, turn=2,
                            source=Provenance.ASSUMED)
        assert rec.verdict == 'pending'
        assert model.get('rules.citymindist') == 2.0
