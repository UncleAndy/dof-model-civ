"""Прогноз на живых данных: цена производства, цена раскрытия, шкала индекса.

Три вещи проверяются здесь ровно потому, что каждая из них однажды уже была
ошибкой:

1. **Срок производства берётся из чисел мира** (`ceil((стоимость − stock)/щиты)`),
   а стоимость — из замера. Тип без измеренной стоимости не предлагается вовсе:
   подставить «один ход» значит выдумать стимул.
2. **Цена раскрытия — разрыв Дженсена** по измеренному разбросу ценностей клеток.
   Содержание скрытой клетки модель и так считает средним, поэтому выгоду даёт
   только опция узнать больше среднего.
3. **Прибавка к городу поднимает индекс.** В переходах стоял потолок `min(1.0, …)`
   — остаток нормализованной шкалы; на шкале опций он делал работу, улучшающую
   клетку, вредной для того самого города, которому она помогает.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from brain.forecast import info
from brain.forecast.live import build_context, reach_tiles
from brain.forecast.state import ForecastState
from brain.forecast.transitions import index_delta
from env.measured_facts import MeasuredFacts


# ── стенд: синтетическое наблюдение, без живого мира ────────────────────────────

def _extractor():
    """Заглушка извлекателя: ценность площадки — её еда (так разброс видно)."""
    return SimpleNamespace(
        my_player_id=0,
        model=None,
        _site_city_value=lambda site, capital: float(site.food),
        _terrain_work_gains=lambda obs, values, map_obs: ({}, {}),
    )


def _dof_state(*, units=(), improvements=None):
    bridge = SimpleNamespace(unit_type_options=dict(units),
                             improvement_options=dict(improvements or {}))
    return SimpleNamespace(state=SimpleNamespace(bridge=bridge, entities={}))


def _obs(*, food=((2, 2, 3.0), (3, 2, 4.0), (4, 2, 5.0)), city=None, units=None):
    out = np.zeros((8, 8, 6), dtype=float)
    for x, y, value in food:
        out[x, y, 0] = value
    return {"map": {"output": out}, "city": city or {}, "unit": units or {}}


def _settler(x=2, y=2):
    return {"7": {"type_rule_name": "Settlers", "owner": 0, "x": x, "y": y,
                  "type_build_cost": 40, "type_move_rate": 1,
                  "type_hp": 20, "health": 20}}


def _city(shield_stock=3, prod_shield=3):
    return {"121": {"id": 121, "owner": 0, "x": 2, "y": 2, "size": 1,
                    "shield_stock": shield_stock, "prod_shield": prod_shield}}


# ── 1. производство ───────────────────────────────────────────────────────────

class TestProductionPricing:
    def _context(self, *, offered, facts=None, dof_units=(), obs_units=None,
                 improvements=None):
        info_dict = {"available_actions": {
            "city": {"121": {"produce_Settlers": True, **offered}},
            "unit": {}, "tech": {}}}
        return build_context(_obs(city=_city(), units=obs_units or _settler()),
                            info_dict,
                            _dof_state(units=dof_units, improvements=improvements),
                            _extractor(),
                            world_model=facts or MeasuredFacts("/tmp/нет-такого.json"))

    def test_turns_come_from_the_world_numbers(self):
        """Живой юнит даёт и опции, и стоимость: срок = ceil((40−3)/3) = 13."""
        ctx = self._context(offered={})
        priced = ctx.vals.productions("city_121")
        assert [name for name, _o, _t in priced] == ["Settlers"]
        option_count, turns = priced[0][1], priced[0][2]
        assert turns == 13
        assert option_count > 0

    def test_an_offered_type_without_a_price_becomes_a_probe(self):
        """Круг «не знаем цену → не строим → не узнаём» разрывается замером.

        Если ход иначе пуст, он тратится на постановку неоцениваемого типа: только
        так у типа появляется шанс стать измеренным (срок читается из числа мира, а
        опции — когда юнит появится живьём).
        """
        ctx = self._context(offered={"produce_Knights": True})
        ctx.vals.productions("city_121")
        assert ctx.probe_action() == ("city", "121", "produce_Knights")

    def test_a_priced_type_is_not_a_probe(self):
        ctx = self._context(offered={})
        ctx.vals.productions("city_121")
        assert ctx.probe_action() is None

    def test_an_unpriced_improvement_is_not_a_probe(self):
        """Постановка улучшения роняет контроллер — это не замер, а поломка.

        Класс типа из наблюдения не выводится: каталог улучшений неполон (`Barracks`
        в нём нет, хотя город этот тип предлагает). Поэтому замер разрешён только
        типам с ДОКАЗАТЕЛЬСТВОМ, что они юниты.
        """
        facts = MeasuredFacts("/tmp/нет-такого.json")
        ctx = self._context(offered={"produce_Barracks": True}, facts=facts,
                            dof_units={}, improvements={"Barracks": 3.0})
        ctx.vals.productions("city_121")
        assert "Barracks" in ctx.unpriced
        assert ctx.probe_action() is None

    def test_a_catalogue_unit_is_probeable(self):
        """Тип из каталога юнитов — доказанный юнит: его мерить безопасно."""
        facts = MeasuredFacts("/tmp/нет-такого.json")
        ctx = self._context(offered={"produce_Battleship": True}, facts=facts,
                            dof_units={"Battleship": 7.85})
        ctx.vals.productions("city_121")
        assert ctx.probe_action() == ("city", "121", "produce_Battleship")

    def test_a_type_learned_alive_is_probeable(self):
        """Тип, который уже видели живьём, тоже доказанный юнит (склад помнит класс)."""
        facts = MeasuredFacts("/tmp/нет-такого.json")
        facts.observe_type("Horsemen", options=5.0, kind="unit")
        ctx = self._context(offered={"produce_Horsemen": True}, facts=facts,
                            dof_units={})
        ctx.vals.productions("city_121")
        assert ctx.probe_action() == ("city", "121", "produce_Horsemen")

    def test_a_type_that_wedged_a_match_is_never_probed_again(self, tmp_path,
                                                              monkeypatch):
        """Цена клина — один матч; выгода — что он не повторится."""
        monkeypatch.setenv("DOF_WEDGED_FILE", str(tmp_path / "wedged.json"))
        import importlib

        import env.wedged as wedged
        importlib.reload(wedged)
        wedged.record_wedged("city", "produce_Battleship", turn=3,
                            context={"agent": "test"})
        # Сначала убеждаемся, что реестр действительно это знает: иначе тест
        # проверял бы не прогноз, а свою же путаницу с путём файла.
        assert wedged.is_wedged("city", "produce_Battleship") is True

        facts = MeasuredFacts("/tmp/нет-такого.json")
        ctx = self._context(offered={"produce_Battleship": True}, facts=facts,
                            dof_units={"Battleship": 7.85})
        ctx.vals.productions("city_121")
        assert ctx.probe_action() is None
        importlib.reload(wedged)       # вернуть реестр в исходное состояние

    def test_a_type_without_a_measured_cost_is_not_offered(self):
        ctx = self._context(offered={"produce_Knights": True})
        assert "Knights" not in [name for name, _o, _t in ctx.vals.productions("city_121")]
        # Тип не выброшен молча: он назван в отчёте, чтобы пробел был виден.
        assert "Knights" in ctx.unpriced

    def test_a_measured_cost_and_a_catalogue_make_a_candidate(self):
        facts = MeasuredFacts("/tmp/нет-такого.json")
        facts.observe_cost("Knights", 30.0)
        ctx = self._context(offered={"produce_Knights": True}, facts=facts,
                            dof_units={"Knights": 6.0})
        priced = ctx.vals.productions("city_121")
        assert ("Knights", 6.0, 9) in [(n, float(o), t) for n, o, t in priced]

    def test_an_offer_without_parameters_is_not_a_candidate(self):
        """Валидность = непустые параметры: `false` — сервер это не предлагает."""
        ctx = self._context(offered={"produce_Knights": False})
        assert "Knights" not in [n for n, _o, _t in ctx.vals.productions("city_121")]

    def test_the_live_unit_is_what_prices_a_type_missing_from_the_catalogue(self):
        """Регрессия на имя поля: `type_rule_name`.

        Каталог извлекателя неполон (на живом наблюдении в нём нет `Settlers` и
        `Warriors` — он строится из спецификаций известных технологий). Цену даёт
        живой юнит того же типа, и связать его с предложением `produce_<Тип>` можно
        только по `type_rule_name`. Пока ключ смотрел на `rule_name`, живые типы
        оставались без цены и производство не предлагалось вовсе.
        """
        ctx = self._context(offered={}, dof_units={})   # каталог пуст намеренно
        priced = ctx.vals.productions("city_121")
        assert [name for name, _o, _t in priced] == ["Settlers"]
        assert ctx.unpriced == set()

    def test_a_type_learned_while_alive_stays_priced_after_it_is_gone(self, tmp_path):
        """Что узнали о типе — записано в склад, и тип остаётся оценимым.

        Ровно тот случай, что ломал прогон: поселенец основывает город и исчезает
        вместе со своими опциями. Каталог его не содержит, живого юнита больше нет —
        и производство новых поселенцев становилось неоценимым, то есть город не мог
        ничего построить.
        """
        facts = MeasuredFacts(tmp_path / "facts.json")
        info_dict = {"available_actions": {"city": {"121": {"produce_Settlers": True}},
                                           "unit": {}, "tech": {}}}
        # Первый ход: поселенец жив — тип опознан, оба числа попали в склад.
        alive = build_context(_obs(city=_city(), units=_settler()), info_dict,
                              _dof_state(), _extractor(), world_model=facts)
        assert alive.vals.productions("city_121"), "живой тип не оценён"

        # Второй ход: поселенца уже нет (основал город) — цена должна остаться.
        gone = build_context(_obs(city=_city(), units={}), info_dict,
                             _dof_state(), _extractor(), world_model=facts)
        priced = gone.vals.productions("city_121")
        assert [name for name, _o, _t in priced] == ["Settlers"]
        assert gone.unpriced == set()

    def test_zero_shields_means_no_prices_at_all(self):
        info_dict = {"available_actions": {"city": {"121": {"produce_Settlers": True}},
                                           "unit": {}, "tech": {}}}
        obs = _obs(city=_city(prod_shield=0), units=_settler())
        ctx = build_context(obs, info_dict, _dof_state(), _extractor(),
                            world_model=MeasuredFacts("/tmp/нет-такого.json"))
        assert ctx.vals.productions("city_121") == []

    def test_a_full_shield_stock_still_takes_one_turn(self):
        """Измерено: при `stock == стоимость` сервер отвечает «1 ход», не «0».

        Он считает и текущий ход. Без нижней границы прогноз обещал бы юнит
        «сейчас» — и обещание было бы неверным.
        """
        info_dict = {"available_actions": {"city": {"121": {"produce_Warriors": True}},
                                           "unit": {}, "tech": {}}}
        obs = _obs(city=_city(shield_stock=10, prod_shield=5),
                   units={"7": {"type_rule_name": "Warriors", "owner": 0, "x": 2, "y": 2,
                                "type_build_cost": 10, "type_move_rate": 1,
                                "type_hp": 10, "health": 10}})
        ctx = build_context(obs, info_dict, _dof_state(), _extractor(),
                            world_model=MeasuredFacts("/tmp/нет-такого.json"))
        priced = ctx.vals.productions("city_121")
        assert [(n, t) for n, _o, t in priced] == [("Warriors", 1)]


# ── 2. цена раскрытия ─────────────────────────────────────────────────────────

class TestResearchPricing:
    """Срок технологии — по драйверу, УСТАНОВЛЕННОМУ замером.

    Правило: `наука_за_ход = round(Σ торговля своих городов × ставка науки / 100)`,
    срок = `ceil((стоимость − накоплено) / наука_за_ход)`. Проверено на двух живых
    прогонах: торговля 1 при ставке 60 → рост +1 (24/24); торговля 3 → рост +2
    (35/35); при этом `Σ торговля`, `floor`, `ceil`, `bulbs` города и `player.science`
    не совпали ни разу. Первый прогон этих двух кандидатов не различал — второй
    различил, и тесты держат именно различающую часть.
    """

    def _context(self, *, trade=3.0, rate=60.0, cost=28.0, done=0.0):
        obs = _obs(city=_city(), units=_settler())
        obs["player"] = {"0": {"researching": 2, "researching_cost": cost,
                               "science": rate, "bulbs_researched": done}}
        obs["tech"] = {"2": {"inv_state": 0, "name": "Monarchy",
                             "sup_units": [{"rule_name": "Phalanx", "build_cost": 30,
                                            "hp": 10, "attack_strength": 1,
                                            "defense_strength": 2, "move_rate": 1,
                                            "firepower": 1, "worker": False}],
                             "sup_improvements": []}}
        obs["city"]["121"]["prod_trade"] = trade
        info_dict = {"available_actions": {"city": {}, "unit": {}, "tech": {}}}
        return build_context(obs, info_dict, _dof_state(), _extractor())

    def test_the_term_follows_trade_times_rate(self):
        """Торговля 3 при ставке 60 % → 2 в ход; 28 стоят 14 ходов."""
        priced = self._context(trade=3.0, rate=60.0, cost=28.0).vals.techs()
        assert len(priced) == 1
        name, gain, turns = priced[0]
        assert name == "tech_2" and gain > 0.0 and turns == 14

    def test_trade_one_gives_one_per_turn(self):
        """Случай первого прогона: торговля 1 → 1 в ход (round(0.6) = 1)."""
        assert self._context(trade=1.0, rate=60.0, cost=28.0).vals.techs()[0][2] == 28

    def test_trade_sum_is_not_the_driver(self):
        """`Σ торговля` опровергнута: при торговле 3 рост равен 2, а не 3."""
        assert self._context(trade=3.0, rate=60.0).vals.techs()[0][2] != 10

    def test_the_city_bulbs_field_is_not_the_driver(self):
        """`bulbs` города — обманка: 3 при торговле 1 (рост был 1, не 3)."""
        obs = _obs(city=_city(), units=_settler())
        obs["player"] = {"0": {"researching": 2, "researching_cost": 12,
                               "science": 60.0, "bulbs_researched": 0}}
        obs["tech"] = {"2": {"inv_state": 0, "name": "Monarchy", "sup_units": [],
                             "sup_improvements": []}}
        obs["city"]["121"]["prod_trade"] = 1.0
        obs["city"]["121"]["bulbs"] = 3.0
        info_dict = {"available_actions": {"city": {}, "unit": {}, "tech": {}}}
        # по драйверу (торговля 1) срок 12; по `bulbs` (3) было бы 4
        priced = build_context(obs, info_dict, _dof_state(), _extractor()).vals.techs()
        assert priced and priced[0][2] == 12

    def test_no_rate_means_no_candidate(self):
        assert self._context(rate=0.0).vals.techs() == []

    def test_the_name_is_the_one_the_wire_expects(self):
        """`tech_2` → `research_tech_2`; имя действия здесь дало бы двойной префикс."""
        from brain.forecast.options import tech_name
        assert tech_name(self._context().vals.techs()[0][0]) == "research_tech_2"


class TestImprovementPricing:
    """Улучшение оценивается стоимостью из спецификаций технологий.

    Стоимость улучшения есть в наблюдении — в `sup_improvements[].build_cost`, там же,
    где `build_cost` у юнитов (Temple 30, Courthouse 60). Поэтому ни замер, ни
    постановка производства (которая роняет контроллер) не нужны.
    """

    def test_an_improvement_is_priced_from_its_specification(self):
        from types import SimpleNamespace
        obs = _obs(city=_city(shield_stock=0, prod_shield=3), units=_settler())
        obs["tech"] = {"10": {"inv_state": 1, "name": "Ceremonial Burial",
                              "sup_units": [],
                              "sup_improvements": [{"rule_name": "Temple",
                                                    "build_cost": 30}]}}
        info_dict = {"available_actions": {
            "city": {"121": {"produce_Temple": True}}, "unit": {}, "tech": {}}}
        ctx = build_context(obs, info_dict, _dof_state(improvements={"Temple": 1.4}),
                            _extractor())
        priced = ctx.vals.productions("city_121")
        assert [name for name, _o, _t in priced] == ["Temple"]
        assert priced[0][2] == 10        # ceil((30 − 0) / 3)

    def test_a_specification_cost_is_not_used_for_the_forecast_units(self):
        """Стоимость из спецификаций законна и для юнитов — это второй источник."""
        from types import SimpleNamespace
        obs = _obs(city=_city(shield_stock=0, prod_shield=3), units=_settler())
        obs["tech"] = {"2": {"inv_state": 1, "name": "Bronze Working",
                             "sup_units": [{"rule_name": "Phalanx",
                                            "build_cost": 30, "hp": 10,
                                            "attack_strength": 1,
                                            "defense_strength": 2,
                                            "move_rate": 1, "firepower": 1,
                                            "worker": False}],
                             "sup_improvements": []}}
        info_dict = {"available_actions": {
            "city": {"121": {"produce_Phalanx": True}}, "unit": {}, "tech": {}}}
        ctx = build_context(obs, info_dict, _dof_state(units={"Phalanx": 4.75}),
                            _extractor())
        priced = ctx.vals.productions("city_121")
        assert [name for name, _o, _t in priced] == ["Phalanx"]


class TestJensenGap:
    def test_gap_in_options_is_the_expected_best_minus_the_belief(self):
        # выборка 0,0,8,0; держим опцию 3: вера = max(3, 2) = 3,
        # ожидаемый максимум = (3+3+8+3)/4 = 4.25 → разрыв 1.25
        assert info.gap_options([0.0, 0.0, 8.0, 0.0], best_known=3.0) == pytest.approx(1.25)

    def test_gap_in_index_units_is_an_index_difference(self):
        """Индекс: `E[ln(max(V,1))] − ln(max(mean(V),1))` — та же шкала, что у решения."""
        # девять пустых клеток и одна находка: вера = «средняя клетка бесполезна»
        # (ln 1 = 0), а розыгрыш даёт ln 8 = 2.079 в одном случае из десяти
        assert info.gap_index([0.0] * 9 + [8.0]) == pytest.approx(
            math.log(8.0) / 10.0)

    def test_a_poor_area_makes_exploration_worth_something(self):
        """Ровно тот случай, который был сломан: локально годного нет вообще.

        В первой редакции (разрыв в опциях) цена выходила нулём, и агент не шёл в
        туман никогда. Здесь вера даёт индекс 0, а редкая находка — положительный.
        """
        poor = [0.0] * 9 + [8.0]
        assert info.gap_index(poor) > 0.0

    def test_a_rich_area_makes_exploration_worth_nothing(self):
        """Если вера уже обещает хорошее, разглядывание не улучшает её в среднем."""
        assert info.gap_index([4.0, 4.0, 4.0]) == 0.0
        assert info.gap_index([1.0, 8.0]) == 0.0

    def test_a_held_option_lowers_the_value_of_looking(self):
        """Чем лучше то, что уже держим, тем меньше смысла разглядывать.

        Первая редакция этого теста ждала обратного — и была неправа: держимая
        опция поднимает базу (`ln 3` вместо `ln 1`), а значит разрыв между верой и
        розыгрышем сужается. Информация ценнее тому, у кого ничего нет.
        """
        gap_with = info.gap_index([0.0] * 9 + [8.0], best_known=0.2)
        gap_without = info.gap_index([0.0] * 9 + [8.0], best_known=0.0)
        assert 0.0 <= gap_with < gap_without
        assert info.gap_index([1.0, 2.0, 3.0], best_known=10.0) == 0.0

    def test_empty_sample_is_zero(self):
        assert info.gap_index([]) == 0.0 and info.gap_options([]) == 0.0

    def test_a_skewed_map_gives_exploration_a_price(self):
        """Много посредственных клеток и редкая находка → средняя вера занижает
        шанс на находку, а держимая приличная площадка делает поиск осмысленным.

        Карта 14×14 и всё вдали от шва: `tile_output` замыкает ОБЕ оси, поэтому у
        края карты площадка «видит» соседей с противоположного края — на этом
        синтетическом примере это сначала и спутало результат.
        """
        poor = [(x, 8, 1.0) for x in range(5, 12)] + [(x, 9, 1.0) for x in range(5, 12)]
        out = np.zeros((14, 14, 6), dtype=float)
        for x, y, value in [(2, 2, 6.0), *poor, (2, 11, 40.0)]:
            out[x, y, 0] = value
        obs = {"map": {"output": out}, "city": {}, "unit": _settler(2, 2)}
        ctx = build_context(obs, {"available_actions": {}}, _dof_state(),
                            _extractor(),
                            world_model=MeasuredFacts("/tmp/нет-такого.json"))
        assert ctx.vals.info_gain((12, 2)) > 0.0           # под туманом
        assert ctx.vals.info_gain((2, 2)) == 0.0           # раскрыта
        # и «цена» не выдумана: она равна разрыву по показанному разбросу
        assert any("разрыв Дженсена" in note and "0.000 (индекс)" not in note
                   for note in ctx.notes)

    def test_revealed_tile_has_no_price_and_hidden_tile_does(self):
        ctx = build_context(_obs(), {"available_actions": {}}, _dof_state(),
                            _extractor(),
                            world_model=MeasuredFacts("/tmp/нет-такого.json"))
        assert ctx.vals.info_gain((2, 2)) == 0.0        # клетка раскрыта
        assert ctx.vals.info_gain((7, 7)) == 0.0        # туман, но вера уже покрывает


# ── 3. шкала индекса ──────────────────────────────────────────────────────────

class TestIndexScale:
    def test_an_addition_to_a_city_raises_the_index(self):
        state = ForecastState(dof={"city_1": 8.0})
        delta = index_delta(state, "city_1", 2.0)
        assert state.dof["city_1"] == pytest.approx(10.0)
        assert delta == pytest.approx(math.log(10.0) - math.log(8.0))
        assert delta > 0.0

    def test_a_city_never_falls_below_one_option(self):
        state = ForecastState(dof={"city_1": 3.0})
        delta = index_delta(state, "city_1", -5.0)
        assert state.dof["city_1"] == pytest.approx(1.0)
        assert delta < 0.0

    def test_an_unknown_entity_is_left_alone(self):
        state = ForecastState(dof={"city_1": 3.0})
        assert index_delta(state, "city_9", 2.0) == 0.0


class TestReach:
    def test_reach_is_the_square_of_the_move_rate_without_the_start(self):
        tiles = reach_tiles((0, 0), 1, (8, 8))
        assert (0, 0) not in tiles
        assert len(tiles) == 8                       # 3×3 минус сама клетка
        assert (7, 0) in tiles                       # карта — цилиндр
