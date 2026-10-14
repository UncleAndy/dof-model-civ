"""Сторожа переноса §13.355: резерв мест (`citymap.c`), его бонусы и ранний выход поиска.

Числа и порядок — из `ai/default/daisettler.c` и `common/aicore/citymap.c`; проверяются
именно они, а не наши удобства.
"""

from __future__ import annotations

import types

import pytest


def test_reserve_city_spot_marks_centre_and_crowds_radius() -> None:
    from brain.ai_default.citymap import CityMap

    cm = CityMap()
    cm.reserve_city_spot(10, 10, 103)
    assert cm.is_reserved(10, 10)                 # место занято
    assert not cm.is_reserved(11, 11)             # сосед лишь «crowded», не занят
    assert cm.raw(11, 11) == 1                    # ровно один город в радиусе
    assert cm.raw(10, 10) == -103


def test_free_city_spot_undoses_both() -> None:
    from brain.ai_default.citymap import CityMap

    cm = CityMap()
    cm.reserve_city_spot(10, 10, 103)
    cm.free_city_spot(10, 10, 103)
    assert not cm.is_reserved(10, 10)
    assert cm.raw(11, 11) == 0


def test_two_reservations_crowd_by_two_and_leave_on_free() -> None:
    from brain.ai_default.citymap import CityMap

    cm = CityMap()
    cm.reserve_city_spot(10, 10, 1)
    cm.reserve_city_spot(12, 10, 2)               # радиусы пересекаются
    assert cm.raw(11, 10) == 2
    cm.free_city_spot(10, 10, 1)
    assert cm.raw(11, 10) == 1


def test_reserve_tile_marks_single_tile_only() -> None:
    from brain.ai_default.citymap import CityMap

    cm = CityMap()
    cm.reserve_tile(20, 20, 105)                  # его `citymap_reserve_tile`
    assert cm.is_reserved(20, 20)
    assert not cm.is_reserved(21, 20)


def test_defense_bonus_is_his_integer_arithmetic() -> None:
    from brain.ai_default.values import result_defense_bonus

    assert result_defense_bonus(402) == 0         # 100 // 403 == 0 — довесок исчезает
    assert result_defense_bonus(100) == 0
    assert result_defense_bonus(50) == 200        # 100//51 * (100//10*20)
    assert result_defense_bonus(50, defense_bonus=0) == 0


def test_naval_bonus_is_twenty_percent_when_ocean_adjacent() -> None:
    from brain.ai_default.values import naval_bonus

    assert naval_bonus(100, True) == 20
    assert naval_bonus(601, True) == 120          # целочисленно, как в C
    assert naval_bonus(100, False) == 0


def test_site_total_order_defense_then_naval_then_remaining() -> None:
    from brain.ai_default.values import (GROWTH_POTENTIAL_DEEMPHASIS, TileValue,
                                         naval_bonus, site_total)

    center = TileValue(food=0.0, shield=0.0, trade=0.0, sum=30.0)
    best = TileValue(food=0.0, shield=0.0, trade=0.0, sum=40.0)
    others = [TileValue(food=0.0, shield=0.0, trade=0.0,
                        sum=GROWTH_POTENTIAL_DEEMPHASIS * 5.0)]   # remaining = 5
    plain = site_total(center, best, others)
    coastal = site_total(center, best, others, ocean_near=True)
    # Его арифметика целиком: base = 30 + 40 = 70; оборонительный довесок
    # `100//71 * (100//10*20) = 200` (при таком малом итоге он велик — у него это
    # «довесок для ничьей»); затем морской от УЖЕ увеличенного итога и лишь потом остаток.
    assert plain == 70.0 + 200 + 5.0
    assert coastal == pytest.approx(270.0 + naval_bonus(270, True) + 5.0)


def _fake_site(x: int, y: int, want: float):
    return types.SimpleNamespace(x=x, y=y, ai_want=want, starved_food=False,
                                 starved_shield=False, best_other_x=x, best_other_y=y,
                                 ocean_adjacent=False)


def test_rank_sites_refuses_spot_reserved_within_citymindist(monkeypatch) -> None:
    """ЕГО правило `city_desirability`: занятая клетка в пределах `citymindist-1` — отказ."""
    from brain.ai_default import founder_destination as fd
    from brain.ai_default.citymap import CityMap

    monkeypatch.setattr('env.site_eval.evaluate_site',
                        lambda map_obs, x, y, **kw: _fake_site(x, y, 500.0))
    cm = CityMap()
    cm.reserve_city_spot(30, 30, 7)               # место занято

    ranked = fd.rank_sites({}, revealed=[(30, 30), (31, 30), (40, 40)],
                           reference=(0, 0), cities=[(30, 30)], mindist=2, reserved=cm)
    got = {(r[0], r[1]) for r in ranked}
    assert (30, 30) not in got                    # сама занятая клетка
    assert (31, 30) not in got                    # в пределах mindist-1 = 1
    assert (40, 40) in got


def test_rank_sites_without_reserved_keeps_everything(monkeypatch) -> None:
    from brain.ai_default import founder_destination as fd

    monkeypatch.setattr('env.site_eval.evaluate_site',
                        lambda map_obs, x, y, **kw: _fake_site(x, y, 500.0))
    ranked = fd.rank_sites({}, revealed=[(30, 30), (40, 40)], reference=(0, 0),
                           cities=[], mindist=2)
    assert {(r[0], r[1]) for r in ranked} == {(30, 30), (40, 40)}
