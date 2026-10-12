"""Порт его оценки эффектов: числа сверяются с его кодом, а эффекты — с правилами мира."""

from __future__ import annotations

from brain.ai_default import effects as fx
from env.rules_costs import EFFECTS


class TestContentValue:
    """`dai_content_effect_value` — его числа: 35 за переведённого, фактор царства."""

    def test_one_unhappy_one_content_citizen_is_thirty_five(self):
        assert fx.content_value(1, unhappy=1, entertainers=0, num_cities=1) == 35.0

    def test_capped_by_unhappy_plus_entertainers(self):
        """`MIN(amount, max_converted + get_entertainers)` — больше перевести нечего."""
        assert fx.content_value(3, unhappy=1, entertainers=0, num_cities=1) == 35.0
        assert fx.content_value(3, unhappy=1, entertainers=1, num_cities=1) == 70.0

    def test_empire_factor_appears_only_with_several_cities(self):
        """При `num_cities > 1` он добавляет `factor * num_cities * amount` (стр. 103–110)."""
        assert fx.content_value(1, unhappy=1, entertainers=0, num_cities=2) == 35.0 + 4 * 2 * 1

    def test_empire_step_bonus_adds_more(self):
        """Если царство больше базового размера, фактор растёт: `cities / MAX(step, 1)`."""
        value = fx.content_value(1, unhappy=1, entertainers=0, num_cities=2,
                                 empire_size_base=3.0, empire_size_step=2.0, cities=7)
        # factor = 2 + 7/2 + 2 = 7; 35 + 7*2*1
        assert value == 35.0 + 7 * 2 * 1


class TestEffectValue:
    def test_no_unhappy_uses_his_thirty(self):
        assert fx.effect_value("No_Unhappy", 1, unhappy=2, entertainers=1) == 3 * 30

    def test_make_happy_uses_five_and_city_counts(self):
        # (0 + 1) * 5 * 1 = 5; царство больше базы (cities 1 > base 0) → +c*amount = 2;
        # и ещё раз +c*amount = 2 (обе строки его кода, стр. 182–187)
        assert fx.effect_value("Make_Happy", 1, unhappy=1, c=2, cities=1) == 9.0

    def test_make_content_is_silent_when_city_has_no_unhappy(self):
        assert fx.effect_value("Make_Content", 1, unhappy=1, c=1, unhappy_free=True) == 0.0

    def test_output_bonus_is_counted_in_base_want_not_here(self):
        """Его перечень `case` без действий: `Output_Bonus` учтён в `base_want()`."""
        assert fx.effect_value("Output_Bonus", 50, unhappy=1, c=1) == 0.0

    def test_zero_amount_is_silent(self):
        assert fx.effect_value("Make_Content", 0, unhappy=1, c=1) == 0.0

    def test_vision_radius_is_a_wild_guess_by_his_own_words(self):
        assert fx.effect_value("City_Vision_Radius_Sq", 5, c=3) == 15.0


class TestWorldGrounding:
    """Эффекты берём из правил мира, а не из воздуха."""

    def test_the_world_has_a_temple_making_content(self):
        temple = [e for e in EFFECTS if e[3] == "Temple"]
        assert temple, "в правилах мира нет эффектов Храма — таблицу надо перечитать"
        assert any(e[0] == "Make_Content" and e[1] == 1 for e in temple)

    def test_type_options_sums_the_effects_of_the_type(self):
        """Сумма по ЭФФЕКТАМ, а не одна запись: у Храма в правилах мира их две."""
        temple = [e for e in EFFECTS if e[3] == "Temple" and e[0] == "Make_Content"]
        assert len(temple) == 2, "мир изменился: у Храма теперь другое число эффектов Content"
        value = fx.type_options(EFFECTS, "Temple", c=1, unhappy=1)
        assert value == 2 * 35.0, "два эффекта Content по 35 на одного недовольного = 70"

    def test_type_options_is_zero_for_a_type_without_effects(self):
        assert fx.type_options(EFFECTS, "Типа-без-эффектов-нет") == 0.0