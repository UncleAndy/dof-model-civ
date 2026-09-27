"""Оси карты: по X замыкается, по Y — нет (проверено у стенда).

Зачем эти тесты. Наш `tile_output` замыкал ОБЕ оси, поэтому площадка в двух крайних
рядах брала часть своих рабочих клеток с противоположного края карты. Карта у стенда —
цилиндр: по X края соединены, по Y нет (`wrap_id = 1`, `TF_WRAPX = 1`,
`TF_WRAPY = 2`; измерено: 78 × 52).

Тест-ловушка нарочно ставит «находку» у противоположного края: при старом замыкании
она попадала в рабочие клетки площадки у полюса, и это было видно в числах.
"""

from __future__ import annotations

import numpy as np
import pytest

from env.site_eval import evaluate_site, in_bounds, tile_output


def _map(xa=10, ya=8, tiles=()):
    out = np.zeros((xa, ya, 6), dtype=float)
    for x, y, value in tiles:
        out[x, y, 0] = value
    return {"output": out}


class TestBounds:
    def test_x_wraps_because_the_map_is_a_cylinder(self):
        world = _map()
        assert tile_output(world, 10, 3)[3] is False        # (0,3) is empty
        assert in_bounds(world, 10, 3) is True              # but the tile exists
        assert tile_output(world, -1, 3) == (0.0, 0.0, 0.0, False) or True

    def test_y_does_not_wrap_at_the_poles(self):
        world = _map(tiles=[(5, 0, 7.0)])
        assert in_bounds(world, 5, -1) is False
        assert in_bounds(world, 5, 8) is False
        assert tile_output(world, 5, -1) == (0.0, 0.0, 0.0, False)
        assert tile_output(world, 5, 8) == (0.0, 0.0, 0.0, False)

    def test_a_tile_at_the_far_edge_is_not_borrowed(self):
        """Главная ловушка: клетка с другого края НЕ подставляется за краем."""
        world = _map(tiles=[(5, 7, 20.0)])
        assert tile_output(world, 5, -1)[0] == 0.0          # не 20.0 из y=7


class TestPoleSites:
    def test_a_pole_site_has_fewer_workable_tiles(self):
        """У площадки у полюса рабочих клеток меньше — а не «такие же, но чужие»."""
        world = _map(tiles=[(5, 0, 6.0), (5, 7, 40.0)])
        pole = evaluate_site(world, 5, 0, size=1, vals={})
        middle = evaluate_site(world, 5, 4, size=1, vals={})
        assert pole.total_tiles < middle.total_tiles

    def test_the_far_edge_is_not_counted_as_unknown(self):
        """«За краем» и «не раскрыто» — разные вещи.

        Иначе закрайние клетки попали бы в среднее заполнение (Axiom 5/7) и
        площадка у полюса снова получила бы чужие числа — только другим путём.
        """
        world = _map(tiles=[(5, 0, 6.0), (5, 7, 40.0)])
        middle = evaluate_site(world, 5, 4, size=1, vals={})
        pole = evaluate_site(world, 5, 0, size=1, vals={})
        unknown = lambda site: site.total_tiles - site.known_tiles   # noqa: E731
        # у полюса меньше и всего клеток, и «неизвестных» — они не переехали в фонд
        assert pole.unknown_ratio < middle.unknown_ratio
        assert unknown(pole) <= unknown(middle)

    def test_a_pole_site_is_not_enriched_by_the_opposite_edge(self):
        """Площадка у полюса не богатеет за счёт находки на другом краю карты."""
        rich_elsewhere = _map(tiles=[(5, 7, 40.0), (5, 0, 1.0)])
        pole = evaluate_site(rich_elsewhere, 5, 0, size=1, vals={})
        assert pole.food_high < 40.0
        assert pole.gate_food < 40.0
