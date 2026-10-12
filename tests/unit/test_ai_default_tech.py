"""Проверка переноса правила технологии встроенного ИИ (§13.189).

Правило: ценность технологии = прирост оценки города, умноженный на коэффициент ИИ 14/8.
Смысл проверки не в арифметике (она тривиальна), а в том, что на НАШЕЙ мере технология
роста оказывается дороже военной — иначе агент и дальше будет 46 раз выбирать Bronze
Working, у которого в правилах мира за спиной чудо и копейщик, а не житница.
"""

from __future__ import annotations

import pytest

from brain.ai_default import tech as ai_tech
from env.entity_extractor import city_options


class _Model:
    """Модель: настоящие факты мира плюс имена построек по номерам."""

    def __init__(self, names: dict[int, str]):
        from env.world_model import default_model
        self._vals = dict(default_model().values())
        self._vals.update({f"improvement.{i}.name": n for i, n in names.items()})

    def values(self) -> dict:
        return self._vals


class TestTechRule:
    def test_want_is_the_ai_conversion_of_the_city_gain(self):
        assert ai_tech.tech_want(10.0, 12.0) == pytest.approx(2.0 * 14 / 8)
        assert ai_tech.tech_want_total([(10.0, 12.0), (5.0, 5.0)]) == pytest.approx(2.0 * 14 / 8)

    def test_rules_table_knows_what_the_techs_unlock(self):
        # Данные из правил мира: Pottery открывает житницу, Bronze Working — чудо и копейщика.
        pottery_b, pottery_u = ai_tech.unlocked_by("Pottery")
        bronze_b, bronze_u = ai_tech.unlocked_by("Bronze Working")
        assert "building_granary" in pottery_b
        assert "building_colossus" in bronze_b
        assert "unit_phalanx" in bronze_u
        # Alphabet не открывает ничего — а мы её исследовали.
        assert ai_tech.unlocked_by("Alphabet") == ((), ())

    def test_name_matching_ignores_the_rules_prefix(self):
        model = _Model({0: "Granary"})
        assert ai_tech.improvement_index(model, "building_granary") == 0
        assert ai_tech.improvement_index(model, "Granary") == 0
        assert ai_tech.improvement_index(model, "Library") is None

    def test_growth_tech_beats_military_tech_on_our_measure(self):
        model = _Model({0: "Granary", 1: "Colossus", 2: "Temple"})
        city = {"size": 1, "surplus_food": 1, "surplus_shield": 3, "surplus_trade": 2,
                "surplus_gold": 1, "improvements": [0, 0, 0]}
        base = city_options(city, model=model)
        pottery = ai_tech.city_want_with(city_options, city, "Pottery", model=model)
        assert pottery > base                      # житница добавляет возможностей
        bronze = ai_tech.city_want_with(city_options, city, "Bronze Working", model=model)
        assert bronze > base                        # чудо тоже, но его цена учтена мерой
        # По правилу встроенного ИИ (через прирост оценки) технология роста не ниже военной:
        # он думает не «что открывает юнит», а «насколько больше могут города».
        assert (pottery - base) >= (bronze - base) - 1e-9

    def test_arrays_from_the_live_stream_do_not_break_the_substitution(self):
        """Живой поток отдаёт `improvements` МАССИВОМ numpy, а не списком.

        Проверка «непустой ли он» у массива не определена и валит прогон
        (`ValueError: truth value of an array with more than one element is ambiguous`).
        В тестах были списки, поэтому дефект дожил до живого прогона и остановил партию
        на первом же ходу — теперь он виден здесь.
        """
        import numpy as np

        model = _Model({0: "Granary"})
        city = {"size": 1, "surplus_food": 1, "surplus_shield": 3, "surplus_trade": 2,
                "surplus_gold": 1, "improvements": np.zeros(3)}
        before = float(city_options(city, model=model))
        after = ai_tech.city_want_with(city_options, city, ["Granary"], model=model)
        assert after >= before                       # счёт не сломался, прирост посчитан
        assert isinstance(city["improvements"], np.ndarray)   # исходный город не испорчен

    def test_sup_improvements_may_be_an_array_of_names(self):
        """Перечень открываемых построек тоже принимается массивом (он же numpy в бою)."""
        import numpy as np

        model = _Model({0: "Granary"})
        city = {"size": 1, "surplus_food": 1, "surplus_shield": 3, "surplus_trade": 2,
                "surplus_gold": 1, "improvements": [0, 0, 0]}
        base = float(city_options(city, model=model))
        got = ai_tech.city_want_with(city_options, city, np.array(["Granary"]), model=model)
        assert got > base