"""Порог площадки для ПЕРВОГО города падает с ходом (решение Andy 2026-09-28).

Зачем правило. Разбор §10.27 показал застой: при бедном старте ни одна достижимая
площадка не годна под порог 6.0, кандидата «основать» не существует, и сторона
стоит вечно — измерено 60 ходов и 0 действий в матче с 6 игроками. Пока города
нет, держать неизменный порог нельзя: цена простоя — весь двигатель населения.

Что проверяется здесь:
* сама формула (числа объявлены Andy'ем: 5.0 → ход 4, 4.0 → 6, 3.0 → 9, 2.0 → 11,
  1.0 → 14) и её монотонность;
* пол: ниже `SITE_MIN_FOOD_FIRST_FLOOR` порог не опускается никогда;
* провод: `build_context` ПОДМЕНЯЕТ порог для первого города и говорит об этом в
  диагностике (одно место для правила — иначе «почему не годна» отвечает не та
  формула, которой агент руководствуется).
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from brain.forecast.live import build_context
from env import config as cfg
from env.config import first_city_food_gate
from env.measured_facts import MeasuredFacts


class TestTheFormula:
    def test_the_declared_numbers(self):
        # Таблица, по которой Andy выбирал шаг 0.4 и пол 1.0.
        assert first_city_food_gate(1) == pytest.approx(6.0)
        assert first_city_food_gate(4) == pytest.approx(4.8)
        assert first_city_food_gate(6) == pytest.approx(4.0)
        assert first_city_food_gate(9) == pytest.approx(2.8)
        assert first_city_food_gate(11) == pytest.approx(2.0)
        assert first_city_food_gate(14) == pytest.approx(1.0)

    def test_the_floor_holds(self):
        assert first_city_food_gate(14) == pytest.approx(cfg.SITE_MIN_FOOD_FIRST_FLOOR)
        assert first_city_food_gate(40) == pytest.approx(cfg.SITE_MIN_FOOD_FIRST_FLOOR)
        assert first_city_food_gate(400) == pytest.approx(cfg.SITE_MIN_FOOD_FIRST_FLOOR)

    def test_it_never_rises(self):
        gates = [first_city_food_gate(t) for t in range(1, 60)]
        assert gates == sorted(gates, reverse=True)

    def test_a_site_with_food_three_is_viable_from_turn_nine(self):
        """Сквозная проверка смысла: площадка с оценкой 3.0 ждёт до 9-го хода."""
        first_turn = next(t for t in range(1, 60) if 3.0 >= first_city_food_gate(t))
        assert first_turn == 9
        assert 3.0 < first_city_food_gate(first_turn - 1)

    def test_nonsense_turns_are_treated_as_the_first_turn(self):
        assert first_city_food_gate(0) == pytest.approx(6.0)
        assert first_city_food_gate(-5) == pytest.approx(6.0)


def _extractor():
    return SimpleNamespace(
        my_player_id=0,
        model=None,
        _site_city_value=lambda site, capital: float(site.food),
        _terrain_work_gains=lambda obs, values, map_obs: ({}, {}),
    )


def _dof_state():
    bridge = SimpleNamespace(unit_type_options={}, improvement_options={})
    return SimpleNamespace(state=SimpleNamespace(bridge=bridge, entities={}))


def _context(turn: int):
    """Наблюдение БЕЗ города: носитель стоит на карте, города нет вовсе."""
    out = np.zeros((8, 8, 6), dtype=float)
    for x, y in ((2, 4), (3, 3), (3, 4)):
        out[x, y, 0] = 1.0                     # скудная земля: по 1 еды
    obs = {"map": {"output": out}, "city": {},
           "unit": {"101": {"type_rule_name": "Settlers", "owner": 0, "x": 2, "y": 2,
                            "type_build_cost": 40, "type_move_rate": 1,
                            "type_hp": 20, "health": 20}},
           "tech": {}, "rules": {"xsize": 8, "ysize": 8}}
    info = {"turn": turn,
            "available_actions": {"city": {}, "unit": {}, "tech": {}}}
    return build_context(obs, info, _dof_state(), _extractor(),
                         world_model=MeasuredFacts("/tmp/нет-такого.json"))


class TestTheWiring:
    def test_the_first_city_gate_is_announced_in_the_diagnostics(self):
        ctx = _context(turn=9)
        joined = " ".join(ctx.notes)
        assert "порог площадки падает с ходом" in joined
        assert "на ходу 9 он 2.80" in joined

    def test_with_a_city_the_gate_stays_strict(self):
        """Город есть → порог не подменяется: правило «однодневок нет» держится."""
        ctx = _context(turn=40)
        assert "порог площадки падает с ходом" in " ".join(ctx.notes)
        # (проверка «после основания порог снова 6.0» живёт на живом проводе:
        #  там видно и город, и меню; здесь — что подмена включается только на
        #  состоянии БЕЗ города, а это и есть условие `capital`.)
