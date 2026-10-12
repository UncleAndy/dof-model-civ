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

    def test_plain_temple_is_thirty_five_not_seventy(self):
        """У Храма ТРИ раздела `Make_Content`, но к простому Храму относится один.

        Мир говорит прямо: `1` без требований, `1` требует `Mysticism`, `2` требует `Oracle`.
        Это измерено чтением правил, и до учёта требований оценка завышала Храм вдвое.
        """
        temple = [e for e in EFFECTS if e[3] == "Temple" and e[0] == "Make_Content"]
        assert len(temple) == 3
        assert {e[7] for e in temple} == {(), ("Mysticism",), ("Oracle",)}
        assert fx.type_options(EFFECTS, "Temple", c=1, unhappy=1) == 35.0

    def test_requirements_open_the_extra_effects(self):
        """С `Mysticism` открывается второй раздел: 35 + 35."""
        held = frozenset({"Mysticism"})
        assert fx.type_options(EFFECTS, "Temple", c=1, unhappy=1, held=held) == 70.0

    def test_type_options_is_zero_for_a_type_without_effects(self):
        assert fx.type_options(EFFECTS, "Типа-без-эффектов-нет") == 0.0


class TestCityWant:
    """`dai_city_want` — его веса: еда 30, щиты 17, загрязнение 20, наука 21.6, золото 18."""

    def test_his_arithmetic_in_one_line(self):
        value = fx.city_want(food=3, shields=2, science=1, gold=4, pollution=1)
        # 3*30 + (2*17 − 1*20) + 1*21.6 + 4*18
        assert value == 90 + (34 - 20) + 21.6 + 72

    def test_tax_above_fifty_makes_gold_heavier(self):
        """Его строка: при налоге > 50 золото идёт ещё × (налог − 40) / 14 (стр. 1487)."""
        value = fx.city_want(food=0, shields=0, science=0, gold=4, tax_rate=60)
        assert value == 4 * 18 * (60 - 40) / 14.0

    def test_zero_shields_do_not_subtract_pollution(self):
        """Его условие `if (prod[O_SHIELD] != 0)`: при нулевых щитах загрязнение не вычитается."""
        assert fx.city_want(food=0, shields=0, science=0, gold=0, pollution=7) == 0.0

    def test_luxury_branch_follows_his_two_settings(self):
        assert fx.city_want(food=0, shields=0, science=0, gold=0, luxury=2,
                            wants_science=True) == 2 * fx.LUXURY_PRIORITY_SCIENCE
        assert fx.city_want(food=0, shields=0, science=1, gold=0, luxury=2,
                            wants_science=False) == 2 * fx.LUXURY_PRIORITY_OTHER + 1


class TestOutputDelta:
    """Семантика прироста — из `common/effects.h`, суммы берутся с эффектов мира."""

    def test_a_percent_bonus_scales_with_the_city_output(self):
        effects = [("Output_Bonus", 25, "Building", "Заводик", "City", "Shield", "effect_x")]
        delta = fx.output_delta(effects, "Заводик", prod={"shields": 8.0}, worked_tiles=4)
        assert delta == {"shields": 8.0 * 25 / 100.0}

    def test_add_tile_is_absolute_per_worked_tile(self):
        effects = [("Output_Add_Tile", 1, "Building", "Гавань", "City", "Trade", "effect_y")]
        delta = fx.output_delta(effects, "Гавань", prod={"trade": 5.0}, worked_tiles=7)
        assert delta == {"trade": 7.0}

    def test_an_effect_without_an_output_kind_is_skipped(self):
        effects = [("Defend_Bonus", 50, "Building", "Стены", "City", "", "effect_z")]
        assert fx.output_delta(effects, "Стены", prod={}, worked_tiles=3) == {}


class TestImprovementValue:
    def test_value_is_the_sum_of_his_two_halves(self):
        """Прирост выходов по `city_want` плюс счастье по `effect_value` — обе половины его."""
        effects = [("Output_Add_Tile", 1, "Building", "Мельница", "City", "Trade", "effect_m"),
                   ("Make_Content", 1, "Building", "Мельница", "City", "", "effect_m2")]
        # Торговлю город делит ставками; берём ставку «всё в науку» — так видно слагаемое.
        value = fx.improvement_value(effects, "Мельница", prod={}, worked_tiles=2,
                                     unhappy=1, trade_split=(1.0, 0.0, 0.0))
        # прирост: 2 клетки × 1 торговли → наука × 21.6; счастье: 35 за одного недовольного
        assert value == 2 * fx.SCIENCE_PRIORITY + 35.0

    def test_trade_without_rates_is_not_counted_silently(self):
        """Нет ставок города — прирост торговли не выдаём за ноль, о нём пишем замечание."""
        fx.NOTES.clear()
        effects = [("Output_Add_Tile", 1, "Building", "Мельница", "City", "Trade", "effect_m")]
        assert fx.improvement_value(effects, "Мельница", prod={}, worked_tiles=2) == 0.0
        assert any("торговли" in note for note in fx.NOTES)

