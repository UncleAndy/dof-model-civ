"""Незнание — не ноль: набивка тумана и пол цены раскрытия (§10.27.1).

Измерено `--sample-sites` (12 996 строк, 12 ходов, 6 игроков): **80.9 %** клеток окна
вокруг старта — площадки, у которых НЕ ВИДНО НИ ОДНОЙ клетки, и все они получали
оценку 0.00 и оптимистичную границу 0.00, то есть годными не бывали никогда
(0 из 10 512). На видимой земле при этом годны 73.4 % площадок при средней оценке
5.36. Здесь проверяется, что ноль в этом случае исчез и что вырожденная выборка
раскрытых клеток больше не обнуляет цену раскрытия.

Числа-набивки — измеренные: запасной источник (когда не раскрыто вообще ничего) —
легенда террейнов (еда 1.00/0.57/0.29 средние, лучшие 2.0/2.0/2.0); пол цены
раскрытия — перевод измеренного ст.откл 1.77 еды в опции (1.27).
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from brain.forecast.live import build_context
from env import config as cfg
from env.measured_facts import MeasuredFacts
from env.site_eval import evaluate_site


def _blank_map(shape=(8, 8, 6)):
    return {"output": np.zeros(shape, dtype=float)}


# ── 1. Набивка полностью нераскрытого окна ───────────────────────────────────

class TestTheUnknownFill:
    def test_a_fully_fogged_window_is_no_longer_zero(self):
        site = evaluate_site(_blank_map(), 4, 4, size=1, vals={})
        assert site.gate_food > 0.0, "оценка нераскрытого окна снова ноль"
        assert site.gate_food_high > 0.0, "граница нераскрытого окна снова ноль"
        assert site.known_tiles == 0

    def test_the_legend_fallback_makes_it_viable(self):
        """Легенда террейнов: лучшая клетка 2.0 еды → три лучших дают ровно порог."""
        site = evaluate_site(_blank_map(), 4, 4, size=1, vals={})
        assert site.gate_food == pytest.approx(cfg.UNKNOWN_FILL_FOOD * 3)   # 3.0
        assert site.gate_food_high == pytest.approx(cfg.UNKNOWN_BEST_FOOD * 3)  # 6.0
        assert site.gate_food_high >= cfg.SITE_MIN_FOOD
        assert site.viable is True

    def test_the_measured_fill_wins_over_the_legend(self):
        vals = {"UNKNOWN_FILL": (1.8, 0.5, 0.4), "UNKNOWN_BEST": (3.0, 1.0, 1.0)}
        site = evaluate_site(_blank_map(), 4, 4, size=1, vals=vals)
        assert site.gate_food == pytest.approx(1.8 * 3)
        assert site.gate_food_high == pytest.approx(3.0 * 3)

    def test_a_visible_window_still_uses_its_own_tiles(self):
        """Набивка НЕ подменяет измеренное: видимое окно считается по своим клеткам."""
        m = _blank_map()
        m["output"][4, 4, 0] = 2.0      # канал 0 — еда (каналы 3–5 всегда нули)
        m["output"][5, 4, 0] = 2.0
        m["output"][4, 5, 0] = 2.0
        site = evaluate_site(m, 4, 4, size=1,
                            vals={"UNKNOWN_FILL": (9.0, 9.0, 9.0),
                                  "UNKNOWN_BEST": (9.0, 9.0, 9.0)})
        assert site.known_tiles == 3
        # Центр даёт max(tile, 1) по каждому каналу, две соседние клетки — по 2 еды:
        # граница берётся по своим видимым, а не по «9.0» из набивки.
        assert site.gate_food_high == pytest.approx(6.0)


# ── 2. Пол цены раскрытия на вырожденной выборке ─────────────────────────────

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


def _context(revealed_food: float):
    """Карта, где РАСКРЫТЫЕ клетки одинаковы: выборка вырождена (разброс нулевой)."""
    out = np.zeros((8, 8, 6), dtype=float)
    for x, y in ((2, 4), (3, 3), (3, 4), (2, 3), (1, 4)):
        out[x, y, 0] = revealed_food
    obs = {"map": {"output": out}, "city": {},
           "unit": {"101": {"type_rule_name": "Settlers", "owner": 0, "x": 2, "y": 2,
                            "type_build_cost": 40, "type_move_rate": 1,
                            "type_hp": 20, "health": 20}},
           "tech": {}, "rules": {"xsize": 8, "ysize": 8}}
    info = {"turn": 1, "available_actions": {"city": {}, "unit": {}, "tech": {}}}
    return build_context(obs, info, _dof_state(), _extractor(),
                         world_model=MeasuredFacts("/tmp/нет-такого.json"))


class TestTheGapFloor:
    def test_the_measured_fill_is_announced(self):
        ctx = _context(revealed_food=2.0)
        joined = " ".join(ctx.notes)
        assert "набивка тумана: по" in joined
        assert "раскрытым клеткам среднее 2.00 еды" in joined

    def test_a_degenerate_sample_gets_the_measured_potential(self):
        """Все раскрытые клетки равны → потенциал берётся из замера, не из нуля."""
        ctx = _context(revealed_food=2.0)
        joined = " ".join(ctx.notes)
        assert "с потенциалом из замера" in joined
        # Цена обязана быть строго положительной: иначе ход в туман отвергается.
        assert ctx.vals.info_gain((5, 5)) > 0.0

    def test_the_potential_is_added_even_when_the_sample_has_a_spread(self):
        """Обычный случай: максимум выборки = удерживаемая площадка → без потенциала
        разрыв тождественно ноль (измерено 0.000 при опциях 0.270 на живом прогоне).
        Потенциал измеренного размера делает цену строго положительной."""
        values = [2.0, 1.0, 3.0, 2.5, 1.5]      # разброс есть, но меньше пола 1.27? нет
        out = np.zeros((8, 8, 6), dtype=float)
        for idx, (x, y) in enumerate(((2, 4), (3, 3), (3, 4), (2, 3), (1, 4))):
            out[x, y, 0] = values[idx]
        obs = {"map": {"output": out}, "city": {},
               "unit": {"101": {"type_rule_name": "Settlers", "owner": 0, "x": 2, "y": 2,
                                "type_build_cost": 40, "type_move_rate": 1,
                                "type_hp": 20, "health": 20}},
               "tech": {}, "rules": {"xsize": 8, "ysize": 8}}
        info = {"turn": 1, "available_actions": {"city": {}, "unit": {}, "tech": {}}}
        ctx = build_context(obs, info, _dof_state(), _extractor(),
                            world_model=MeasuredFacts("/tmp/нет-такого.json"))
        assert ctx.vals.info_gain((5, 5)) > 0.0

    def test_the_floor_is_the_measured_number(self):
        assert cfg.INFO_GAP_FLOOR_OPTIONS == pytest.approx(1.27)
        # Перевод замера: base 3 × m2 1.2 × CITY_M1_FOOD 0.2 × ст.откл 1.77 еды.
        assert (3.0 * 1.2 * cfg.CITY_M1_FOOD * 1.77) == pytest.approx(1.27, abs=0.01)