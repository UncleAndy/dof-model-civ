"""Цена угрозы: чтобы потеря сущности была видна ДО потери (аксиомы 3, 4, 5).

ЗАЧЕМ. Измерено (§10.69): в партии 9000 агент потерял всё — 0 городов, 0 юнитов, счёта нет.
Это слепота модели, а не неудача политики: индекс `Σ ln(DoF)` не имеет цены за приближение
сущности к `DoF = 0`, поэтому в нём нет ни одного защитного действия. Здесь эта цена появляется.

ГЕОМЕТРИЯ — ИЗМЕРЕНА, не предположена (`scripts/v2_dir8_probe.py`, 8 партий, по одному шагу):

    goto_0 = (-1,-1) NW      goto_4 = (+1, 0) E
    goto_1 = ( 0,-1) N       goto_5 = (-1,+1) SW
    goto_2 = (+1,-1) NE      goto_6 = ( 0,+1) S
    goto_3 = (-1, 0) W       goto_7 = (+1,+1) SE

Код вендора подтверждает, что `goto_N` — **один шаг** в направлении dir8
(`unit_actions.py:1659 ActGoto`, `mapstep(ptile, dir8)`), поэтому цена угрозы считается по
фактическому смещению, а не по догадке о «пути».

ОБЪЯВЛЕНО ДО ДАННЫХ:

* **T1. Угроза** — чужая сущность, наблюдённая с атакой (`attack > 0`). Мирные чужие не угроза
  (решение Andy: мирные плюсуются к общему DoF).
* **T2. Досягаемость** — Chebyshev-расстояние с замыканием по X (карта-цилиндр), делённое на
  опубликованную `move_rate` угрозы; если ходов ≤ τ, сущность **под ударом**.
* **T3. Цена** — миникас (аксиома 5): если удар состоится, наша сущность теряется, и индекс
  падает на её слагаемое `ln(DoF)`. Никаких вероятностей я не выдумываю — берётся худший случай.
* **T4. Ценность защитного действия = уменьшение цены**: уход из-под удара (шаг `goto_N`, который
  выводит из досягаемости) сохраняет `ln(DoF)` сущности; основание города под ударом — наоборот,
  добавляет к цене `ln(DoF)` нового города.
* **T5. Происхождение** — «выведено (миникас по наблюдённой угрозе)»: это не замер потери, а
  расчёт по измеренным расстояниям, скоростям и угрозам. В протоколе помечается явно.
"""
from __future__ import annotations

import math
from typing import Optional

from .families import action_family
from .knowledge import KnowledgeGraph

#: Измерено пробой (см. заголовок): dir8 -> смещение (dx, dy)
DIR8_MEASURED = {
    "goto_0": (-1, -1), "goto_1": (0, -1), "goto_2": (1, -1), "goto_3": (-1, 0),
    "goto_4": (1, 0), "goto_5": (-1, 1), "goto_6": (0, 1), "goto_7": (1, 1),
}

#: ОКНО УДАРА — объявлено отдельно от τ, и вот почему (измерено): приорная τ = 5.8 при скорости
#: угрозы 3 означает досягаемость ≈17 клеток, то есть «под ударом» оказывается почти вся карта,
#: и сигнал угрозы перестаёт что-либо различать (цена риска одинакова везде, а уход на 3 шага
#: всё равно «под ударом»). Поэтому угроза считается по сроку, за который удар может состояться:
#: **1 ход**. Это не подгонка, а отказ от величины, которая не различает.
STRIKE_TURNS = 1.0


def cheb(ax: int, ay: int, bx: int, by: int, xsize: int) -> int:
    """Расстояние Чебышёва с замыканием X (карта-цилиндр, wrap_id=1)."""
    dx = abs(ax - bx)
    if xsize:
        dx = min(dx, xsize - dx)
    return max(dx, abs(ay - by))


def threats(graph: KnowledgeGraph) -> list[dict]:
    """T1: наблюдённые чужие сущности с атакой."""
    out = []
    for e in graph.by_kind("unit"):
        if e.is_own or e.attrs.get("x") is None:
            continue
        a = e.attrs.get("attack")
        if isinstance(a, (int, float)) and a > 0:
            out.append({"eid": e.eid, "attack": float(a), "x": e.attrs["x"], "y": e.attrs["y"],
                        "move_rate": e.attrs.get("move_rate") or 1})
    return out


def exposure(graph: KnowledgeGraph, tau: float = STRIKE_TURNS) -> dict[str, dict]:
    """T2: наши сущности под ударом -> чем и за сколько ходов."""
    xsize = int((graph.world or {}).get("xsize") or 0)
    th = threats(graph)
    out: dict[str, dict] = {}
    if not th:
        return out
    for e in list(graph.by_kind("unit")) + list(graph.by_kind("city")):
        if not e.is_own or e.attrs.get("x") is None:
            continue
        for t in th:
            d = cheb(e.attrs["x"], e.attrs["y"], t["x"], t["y"], xsize)
            turns = d / float(max(1, t["move_rate"]))
            if turns <= tau:
                prev = out.get(e.eid)
                if prev is None or turns < prev["ходов"]:
                    out[e.eid] = {"угроза": t["eid"], "клеток": d, "ходов": round(turns, 1)}
    return out


def risk_price(graph: KnowledgeGraph, dof_of, tau: float) -> tuple[float, dict]:
    """T3: цена риска = сумма ln(DoF) наших сущностей под ударом (миникас)."""
    exp = exposure(graph, tau)
    price = 0.0
    detail: dict = {}
    for eid, info in exp.items():
        e = graph.entity(eid)
        if e is None:
            continue
        v, origin = dof_of(graph, e)
        if v and v > 0:
            price += math.log(v)
            detail[eid] = {**info, "DoF": v, "происхождение": origin}
    return price, detail


def movement_gain(graph: KnowledgeGraph, ctrl: str, action: str, actor: str,
                  dof_of, tau: float = STRIKE_TURNS,
                  steps_count: int = 1) -> tuple[float, str]:
    """T4: сколько DoF сохраняет уход из-под удара.

    `steps_count` — сколько шагов подряд в этом направлении делается (план, решение D2). Это
    измеренно важно: против угрозы со скоростью 3 один шаг из-под удара **не выводит**
    (расстояние 1 → 2 при досягаемости 3 клетки за ход), а три шага выводят. Поэтому путь выхода
    строится планом, а оценивается его конечная точка.
    """
    if action not in DIR8_MEASURED or ctrl != "unit":
        return 0.0, ""
    e = graph.entity(f"unit:{actor}")
    if e is None or e.attrs.get("x") is None:
        return 0.0, ""
    before = exposure(graph, tau)
    if e.eid not in before:
        return 0.0, ""                      # не под ударом — защищаться нечем
    v, _ = dof_of(graph, e)
    if not v or v <= 0:
        return 0.0, ""
    dx, dy = DIR8_MEASURED[action]
    xsize = int((graph.world or {}).get("xsize") or 0)
    nx = e.attrs["x"]
    ny = e.attrs["y"]
    for _ in range(max(1, steps_count)):
        nx = (nx + dx) % xsize if xsize else nx + dx
        ny = ny + dy
    still = False
    for t in threats(graph):
        if cheb(nx, ny, t["x"], t["y"], xsize) / float(max(1, t["move_rate"])) <= tau:
            still = True
            break
    if still:
        return 0.0, (f"{action} ×{steps_count}: остаёмся под ударом "
                     f"({before[e.eid]['угроза']} в {before[e.eid]['клеток']} клетках)")
    return math.log(v), (f"{action} ×{steps_count}: выходим из-под удара "
                         f"({before[e.eid]['угроза']} в {before[e.eid]['клеток']} клетках) → "
                         f"сохраняем DoF {v:g} (миникас, аксиома 5)")


def founding_risk(graph: KnowledgeGraph, action: str, actor: str,
                  dof_of, impute, tau: float = STRIKE_TURNS) -> tuple[float, str]:
    """T4: цена основания города под ударом (миникас: удар состоится — город теряется)."""
    if action_family(action) != "build_city":
        return 0.0, ""
    e = graph.entity(f"unit:{actor}")
    if e is None or e.attrs.get("x") is None:
        return 0.0, ""
    xsize = int((graph.world or {}).get("xsize") or 0)
    in_reach = None
    for t in threats(graph):
        d = cheb(e.attrs["x"], e.attrs["y"], t["x"], t["y"], xsize)
        turns = d / float(max(1, t["move_rate"]))
        if turns <= tau:
            in_reach = (t["eid"], d, round(turns, 1))
            break
    if in_reach is None:
        return 0.0, ""
    v, _n = impute(graph, "city")
    if not v or v <= 0:
        return 0.0, f"город под ударом ({in_reach[0]}), но его DoF неизвестен — считать нечем"
    return -math.log(v), (f"город встанет под удар ({in_reach[0]} в {in_reach[1]} клетках, "
                          f"{in_reach[2]} ход.) → минус DoF города (миникас, аксиома 5)")