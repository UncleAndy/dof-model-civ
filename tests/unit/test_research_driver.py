"""Драйвер науки в извлекателе: торговля × ставка, и живые ключи — целые.

Два дефекта, которые здесь закрепляются как исправленные:

1. `_tech_research_gains` брал науку за ход из `player['science']` (60) — поля,
   которое прогресс не двигает вообще. Измерено на трёх картах: рост
   `bulbs_researched` равен `round(Σ prod_trade × ставка / 100)`. Из-за этого
   числа извлекателя по исследованиям были завышены примерно на два порядка.
2. `obs['player']` в живом потоке ключуется ЦЕЛЫМИ (`0`, `1`, …), а `city` —
   строками. Поиск по строке молча возвращал пустую запись, и срок технологии
   подменялся номинальным.

Тесты держат оба: если кто-то вернёт `player['science']` как выход или снова
скопирует поиск игрока в другое место, здесь это станет видно.
"""

from __future__ import annotations

import numpy as np

from env.entity_extractor import GameStateExtractor, player_record


def _obs(*, player_keys=("0",), trade=3.0, rate=60.0, cost=20.0, progress=0.0,
         researching=2):
    out = np.zeros((6, 6, 6), dtype=float)
    out[2, 2, 0] = 3.0
    return {
        "map": {"output": out},
        "player": {key: {"researching": researching, "researching_cost": cost,
                         "bulbs_researched": progress, "science": rate}
                   for key in player_keys},
        "city": {"121": {"id": 121, "owner": 0, "x": 2, "y": 2, "size": 1,
                         "prod_trade": trade, "shield_stock": 0, "prod_shield": 1}},
        "tech": {"2": {"name": "Monarchy", "inv_state": 0, "reqs": [],
                       "sup_units": [{"rule_name": "Phalanx", "build_cost": 30,
                                      "hp": 10, "attack_strength": 1,
                                      "defense_strength": 2, "move_rate": 1,
                                      "firepower": 1, "worker": False}],
                       "sup_improvements": []}},
        "unit": {},
    }


class TestPlayerRecord:
    def test_integer_keys_are_found(self):
        """Живой поток: ключи целые. Строковый поиск тут возвращал пусто."""
        assert player_record(_obs(player_keys=(0,)), 0) != {}

    def test_string_keys_are_found(self):
        """Сохранённое наблюдение: ключи строки."""
        assert player_record(_obs(player_keys=("0",)), 0) != {}

    def test_the_single_player_fallback_works(self):
        assert player_record(_obs(player_keys=(7,)), 0) != {}


class TestResearchGain:
    def test_the_term_follows_trade_times_rate(self):
        """Торговля 3, ставка 60 % → 2 в ход; стоимость 20 → 10 ходов.

        Выигрыш = опции − база, делённые на срок (контракт извлекателя: это СКОРОСТЬ).
        """
        extractor = GameStateExtractor(my_player_id=0)
        gains = extractor._tech_research_gains(_obs(trade=3.0, rate=60.0, cost=20.0))
        assert "tech_2" in gains
        unlocked = gains["tech_2"] * 10.0        # срок 10 ходов
        assert unlocked > 1.0                    # технология что-то открывает

    def test_the_term_is_the_trade_driven_one_and_not_the_rate(self):
        """Точная сверка: выигрыш = открытые опции / 10 (срок), а не / 1 (ставка).

        Если бы наука за ход бралась из `player['science']` = 60, срок вышел бы 1 ход
        и выигрыш был бы вдесятеро больше — то самое завышение на два порядка.
        """
        import pytest

        from env.entity_extractor import tech_options

        extractor = GameStateExtractor(my_player_id=0)
        obs = _obs(trade=3.0, rate=60.0, cost=20.0)
        gains = extractor._tech_research_gains(obs)
        unlocked = (tech_options(obs["tech"]["2"], as_known=True,
                                 model=extractor.model)
                    - extractor.model.values()["TECH_BASE_OPTIONS"])
        assert gains["tech_2"] == pytest.approx(unlocked / 10.0)

    def test_no_science_output_means_no_price(self):
        """Нет торговли — нет выхода науки: срок неизвестен, цену не публикуем."""
        extractor = GameStateExtractor(my_player_id=0)
        assert extractor._tech_research_gains(_obs(trade=0.0)) == {}

    def test_a_progress_already_made_shortens_the_term(self):
        extractor = GameStateExtractor(my_player_id=0)
        fresh = extractor._tech_research_gains(_obs(cost=20.0, progress=0.0))
        ahead = extractor._tech_research_gains(_obs(cost=20.0, progress=18.0))
        assert ahead["tech_2"] > fresh["tech_2"]      # срок короче → скорость выше
