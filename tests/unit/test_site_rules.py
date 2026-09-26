"""Правила выбора клеток: проверка до того, как по ним делать выводы.

Если селектор ошибается, вывод «игра использует правило X» будет ложным, поэтому
проверяются именно те случаи, где правила различимы.
"""
from __future__ import annotations

import pytest

from env.site_rules import (
    PER_CHANNEL_RULE,
    VERDICT_MIN_ROWS,
    VERDICT_MIN_SHARE,
    all_rules,
    indices_for,
    predict,
    verdict,
)
from env.site_eval import CITY_CENTRE_MIN
from env.site_rules import _key_food, _key_shield

#: Центр + две клетки, специально подобранные так, чтобы правила расходились:
#: A — щитовая, B — сытная и торговая.
TILES = [
    (2, 0, 0),    # центр
    (3, 10, 0),   # A
    (5, 0, 9),    # B
]


class TestSelection:
    def test_the_centre_is_always_worked(self):
        for key in (_key_food, _key_shield):
            assert 0 in indices_for(TILES, size=1, key=key)

    def test_size_selects_that_many_extra_tiles(self):
        assert sorted(indices_for(TILES, size=1, key=_key_food)) == [0, 2]
        assert sorted(indices_for(TILES, size=2, key=_key_food)) == [0, 1, 2]

    def test_zero_size_still_works_only_the_centre(self):
        assert indices_for(TILES, size=0, key=_key_food) == [0]

    def test_an_empty_site_predicts_nothing(self):
        assert predict([], size=2, rule=PER_CHANNEL_RULE) == (0.0, 0.0, 0.0)


class TestRulesDiffer:
    # Здесь проверяется ВЫБОР клеток, поэтому поправка центра выключена
    # (`centre_min=0`): иначе тест смешивал бы две разные вещи.

    def test_per_channel_gives_each_channel_its_own_best_set(self):
        # еда берёт B, щиты берут A, торговля берёт B
        assert predict(TILES, 1, PER_CHANNEL_RULE, centre_min=0) == (7.0, 10.0, 9.0)

    def test_single_food_takes_one_set_for_all_channels(self):
        # набор по еде: центр + B → щитов 0, торговли 9
        assert predict(TILES, 1, "single_food", centre_min=0) == (7.0, 0.0, 9.0)

    def test_single_shield_takes_the_shield_set(self):
        assert predict(TILES, 1, "single_shield", centre_min=0) == (5.0, 10.0, 0.0)

    def test_the_two_families_are_not_the_same_prediction(self):
        per_channel = predict(TILES, 1, PER_CHANNEL_RULE, centre_min=0)
        single = predict(TILES, 1, "single_food", centre_min=0)
        assert per_channel != single, "иначе различить правила по данным нельзя"

    def test_rule_list_contains_both_families(self):
        rules = all_rules()
        assert PER_CHANNEL_RULE in rules
        assert any(r.startswith("single_") for r in rules)
        assert len(rules) >= 6

    def test_unknown_rule_is_an_error_not_a_silent_wrong_answer(self):
        # Тихая подмена правила — это как раз то, из-за чего вывод может стать
        # ложным; лучше падение.
        with pytest.raises(KeyError):
            predict(TILES, 1, "single_nonexistent")


class TestCentreMinimum:
    """Центр города даёт не меньше 1 по каждому каналу (измерено)."""

    def test_the_centre_is_raised_to_the_minimum_on_every_channel(self):
        tiles = [(1, 1, 0), (0, 0, 0)]
        got = predict(tiles, 0, PER_CHANNEL_RULE)
        assert got == (1.0, 1.0, 1.0)

    def test_the_centre_is_not_lowered(self):
        tiles = [(3, 4, 5)]
        assert predict(tiles, 0, PER_CHANNEL_RULE) == (3.0, 4.0, 5.0)

    def test_the_correction_is_a_minimum_not_a_bonus(self):
        # «Плюс один» дало бы 4/8 строк против 6/8 у минимума — это разные
        # гипотезы, и проверяются они разными числами.
        tiles = [(3, 4, 5)]
        got = predict(tiles, 0, PER_CHANNEL_RULE)
        assert got != (4.0, 5.0, 6.0)

    def test_an_unrevealed_centre_stays_unrevealed(self):
        # Ноль в центре может значить «не знаем»; превращать незнание в единицу
        # нельзя (иначе неразведанная площадка выглядит лучше, чем она есть).
        tiles = [(0, 0, 0), (2, 2, 2)]
        assert predict(tiles, 1, PER_CHANNEL_RULE) == (2.0, 2.0, 2.0)

    def test_only_tiles_other_than_the_centre_are_left_alone(self):
        tiles = [(1, 1, 1), (0, 0, 0), (2, 0, 0)]
        # Центр поднят до 1, соседняя нулевая клетка — нет. Город при size=1
        # обрабатывает центр + 1 клетку, и это (2,0,0): еда 1+2=3, щиты/торговля
        # только от центра.
        assert predict(tiles, 1, PER_CHANNEL_RULE) == (3.0, 1.0, 1.0)
        assert CITY_CENTRE_MIN == 1.0


class TestVerdictThresholds:
    """Порог вердикта задан ДО данных и не двигается под результат."""

    def _exact(self, shares: dict[str, float], n: int) -> dict[str, list[int]]:
        return {r: [int(s * n) for _ in range(3)] for r, s in shares.items()}

    def test_too_few_rows_means_no_verdict(self):
        # Именно этот случай случился на 8 строках, когда скрипт едва не объявил
        # правило найденным по 4 совпадениям из 24.
        v = verdict(self._exact({"single_food": 0.9, "per_channel": 0.1}, 8), 8)
        assert v["ok"] is False and v["rule"] is None
        assert str(VERDICT_MIN_ROWS) in v["reason"]

    def test_a_clear_winner_on_every_channel_is_a_verdict(self):
        v = verdict(self._exact({"single_food": 0.9, "per_channel": 0.2}, 30), 30)
        assert v["ok"] is True and v["rule"] == "single_food"

    def test_a_weak_best_rule_is_not_a_verdict(self):
        v = verdict(self._exact({"single_food": 0.4, "per_channel": 0.3}, 30), 30)
        assert v["ok"] is False

    def test_a_rule_that_fails_one_channel_is_not_the_games_rule(self):
        exact = {"single_food": [30, 30, 2], "per_channel": [5, 5, 5]}
        v = verdict(exact, 30)
        assert v["ok"] is False
        assert "канал" in v["reason"]

    def test_rules_that_are_too_close_are_not_distinguishable(self):
        exact = {"single_food": [28, 28, 28], "single_total": [26, 26, 26]}
        v = verdict(exact, 30)
        assert v["ok"] is False
        assert VERDICT_MIN_SHARE <= 1.0
