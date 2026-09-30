"""Исследование как цель: движение к нераскрытой зоне с ценой из ИЗМЕРЕННОГО.

ЗАЧЕМ (измерено, §10.81). Видео показало: агент не двигает юниты **вообще** — 0 действий движения
из 650 решений. Корень структурный: пути движения появлялись только как `escape` (нужно наблюдённое
нападение) и `probe` (нужно ненаблюдённое семейство эффекта). Своей цели у движения не было, поэтому
коридор занимал канал города, а юниты стояли.

ПОЧЕМУ ЭТО НЕ «ПОЛЕЗНОСТЬ РАДИ ПОЛЕЗНОСТИ». Мирные чужие сущности ПЛЮСУЮТСЯ к общему DoF
(решение Andy, §10.33), а раскрытая клетка — единственный способ увидеть чужие города, юниты и
ресурсы. Значит исследование увеличивает измеряемый индекс, и цену этому можно дать **измерением**,
а не выдумкой:

* сколько клеток раскрывает одно движение — ИЗМЕРЕНО (эффект `unit/goto`: `revealed_delta` на
  использование; в базе уже есть 23 клетки за 66 использований);
* сколько сущностей приходит на раскрытую клетку — ИЗМЕРЯЕТСЯ нашим же опытом: агент каждый ход
  записывает, сколько сущностей появилось в графе и сколько клеток раскрылось (`связь discovery`);
* ценность обнаруженной сущности — `ln(DoF)` известных чужих сущностей (мирные плюсуются).

Пока измерений нет, цена не выдумывается: возвращается ноль с причиной «нет измерений» — и в дело
вступает проба, которая эти измерения и добудет.
"""
from __future__ import annotations

import math
from typing import Optional

from .families import action_family
from .knowledge import KnowledgeGraph
from .threat import cheb, offset_of

#: Ближе какого расстояния нераскрытая клетка считается «рядом» (структурное правило).
FRONTIER_REACH = 12


def unrevealed_near(graph: KnowledgeGraph, x: int, y: int) -> Optional[tuple[int, int]]:
    """Ближайшая нераскрытая клетка к точке — по опубликованной миром карте раскрытия."""
    w = graph.world or {}
    xsize, ysize = int(w.get("xsize") or 0), int(w.get("ysize") or 0)
    if not xsize or not ysize:
        return None
    revealed = w.get("раскрытие")
    if not revealed:
        return None
    best = None
    for i in range(xsize):
        for j in range(ysize):
            try:
                if revealed[i][j]:
                    continue
            except (IndexError, TypeError):
                continue
            d = cheb(x, y, i, j, xsize)
            if best is None or d < best[0]:
                best = (d, i, j)
    return None if best is None else (best[1], best[2])


def explore_gain(graph: KnowledgeGraph, action: str, actor: str, dof_of,
                 impute_foreign) -> tuple[float, str]:
    """Цена движения, раскрывающего карту, — из измеренных величин.

    `клеток_на_ход` × `сущностей_на_клетку` × ln(DoF обнаруженной сущности). Все три множителя
    измерены; если хоть один неизвестен, цена равна нулю с указанием причины (не выдумывается).
    """
    if action_family(action) != "goto" and not str(action).startswith("goto_"):
        return 0.0, ""
    off = offset_of(action)
    if off is None:
        return 0.0, ""
    e = graph.entity(f"unit:{actor}")
    if e is None or e.attrs.get("x") is None:
        return 0.0, ""
    xsize = int((graph.world or {}).get("xsize") or 0)
    nx = (e.attrs["x"] + off[0]) % xsize if xsize else e.attrs["x"] + off[0]
    ny = e.attrs["y"] + off[1]
    target = unrevealed_near(graph, nx, ny)
    if target is None:
        return 0.0, ""
    before = unrevealed_near(graph, e.attrs["x"], e.attrs["y"])
    d_before = cheb(e.attrs["x"], e.attrs["y"], target[0], target[1], xsize)
    d_after = cheb(nx, ny, target[0], target[1], xsize)
    if d_after >= d_before:
        return 0.0, f"{action}: не приближает к нераскрытой клетке ({d_before} → {d_after})"

    tiles, tsrc = tiles_per_move(graph)
    if tiles is None:
        return 0.0, f"{action}: цена исследования неизвестна — {tsrc}"
    ent, esrc = entities_per_tile(graph)
    if ent is None:
        return 0.0, f"{action}: цена исследования неизвестна — {esrc}"
    val, vsrc = impute_foreign(graph)
    if not val or val <= 0:
        return 0.0, f"{action}: ценность обнаруженной сущности неизвестна ({vsrc})"
    gain = tiles * ent * math.log(val)
    return gain, (f"{action}: приближает к нераскрытой ({d_before} → {d_after}); "
                  f"цена из измерения: {tiles:.2f} клетки/ход × {ent:.3f} сущн./клетка × "
                  f"ln(DoF {val:g}) = {gain:+.3f}")


def tiles_per_move(graph: KnowledgeGraph) -> tuple[Optional[float], str]:
    """Измерено: сколько клеток раскрывает одно движение (`revealed_delta` в эффекте `unit/goto`)."""
    rec = graph.effect_of("unit", "goto")
    if not rec:
        return None, "эффект unit/goto ещё не наблюдался"
    seen = int(rec.get("seen") or 0)
    d = (rec.get("change_counts") or {}).get("revealed_delta")
    if not seen or d is None:
        return None, "раскрытие в эффекте unit/goto не встречалось"
    return max(0.0, float(d) / float(seen)), f"наблюдено {seen} ход(ов) движения"


def entities_per_tile(graph: KnowledgeGraph) -> tuple[Optional[float], str]:
    """Измерено нашим опытом: сколько сущностей появляется на одну раскрытую клетку."""
    recs = [r for r in (graph.observed.get("discovery") or []) if isinstance(r, dict)]
    tiles = sum(int(r.get("клеток") or 0) for r in recs)
    ents = sum(int(r.get("сущностей") or 0) for r in recs)
    if tiles <= 0:
        return None, "связь discovery ещё не накоплена"
    return ents / float(tiles), f"накоплено {tiles} клеток и {ents} сущностей"