"""DOF-фильтр (calculus): шаги 2–4 спеки и протокол решения (Proof of Implementation).

ЧТО ЗДЕСЬ РЕШАЕТСЯ (объявлено до данных):

* **Индекс:** `Σ ln(DoF_семейное)` по множеству `calc` — чистое произведение по Нэшу, как в спеке.
  Берём **семейное** число (решение D1): `goto_0..7` — одна возможность, а не восемь.
* **Множество `calc`:** сущности видов «юнит», «город», «канал» — свои и чужие (решение Andy:
  мирные чужие **плюсуются** к общему DoF). Технологии, улучшения, игроки и клетки не входят:
  у них нет собственного набора переходов, то есть нет своего DoF.
* **Неизвестный DoF моделируется средним по известным того же вида** (правило проекта:
  незнание ≠ ноль), и это честно помечается в протоколе как «выведено».
* **Сущность без переходов сейчас** (DoF = 0) исключается из суммы с записью причины. Это не
  смерть сущности: у нас DoF — накопленный набор возможностей, и ноль означает «сейчас нечего».
* **ΔT = 0.0.** Прерывать активные процессы в нашем наборе действий пока нечем (городские
  действия миру не предлагаются). Измеримая часть ΔT — щиты в очереди города (`shield_stock`) —
  пишется в протокол, чтобы не потерялась.
* **Выбор:** наибольший `NetDelta > 0`; если таких нет — **пробный путь** (прирост знания,
  аксиома 5); если и его нет — закрыть ход. Заморозка недопустима.

Протокол пишется всегда и целиком: это и есть Proof of Implementation из спеки.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from .families import action_family
from .knowledge import KnowledgeGraph
from .projection import project

#: виды сущностей, у которых есть собственный набор переходов
CALC_KINDS = ("unit", "city", "controller")

#: ΔT (энтропия переключения). Объявлено: 0.0 — прерывать пока нечего.
DT_DECLARED = 0.0


def _family_dof(e) -> Optional[float]:
    """Семейный DoF сущности, если он измерен."""
    fam = e.attrs.get("dof_families")
    if isinstance(fam, int) and fam > 0:
        return float(fam)
    if e.dof and e.dof.comparable and e.dof.v and e.dof.v > 0:
        return float(e.dof.v)
    return None


def dof_of(graph: KnowledgeGraph, e) -> tuple[Optional[float], str]:
    """DoF сущности и происхождение числа."""
    if e.kind == "unit" and e.name:
        te = graph.entity(f"unit_type:{e.name}")
        if te is not None:
            v = _family_dof(te)
            if v is not None:
                return v, ("измерено" if e.is_own else "выведено (аналогия)")
    v = _family_dof(e)
    if v is not None:
        return v, "измерено"
    return None, "неизвестно"


def impute(graph: KnowledgeGraph, kind: str) -> tuple[Optional[float], int]:
    """Среднее по известным того же вида — как моделировать незнание (не нулём)."""
    vals = []
    for e in graph.by_kind(kind):
        v, _ = dof_of(graph, e)
        if v is not None:
            vals.append(v)
    if not vals:
        return None, 0
    vals.sort()
    return vals[len(vals) // 2], len(vals)


def calc_set(graph: KnowledgeGraph) -> tuple[list[dict], list[dict]]:
    """Шаг 2 спеки: какие сущности входят в расчёт, какие исключены и почему."""
    included: list[dict] = []
    excluded: list[dict] = []
    for kind in CALC_KINDS:
        for e in sorted(graph.by_kind(kind), key=lambda x: x.eid):
            v, origin = dof_of(graph, e)
            if v is None:
                imp, n = impute(graph, kind)
                if imp is None or imp <= 0:
                    excluded.append({"eid": e.eid, "why": "DoF неизвестен и среднего нет",
                                     "origin": "неизвестно"})
                    continue
                included.append({"eid": e.eid, "dof": imp, "origin": f"выведено (среднее по {n})"})
            elif v <= 0:
                excluded.append({"eid": e.eid, "why": "переходов сейчас нет (не смерть)",
                                 "origin": origin})
            else:
                included.append({"eid": e.eid, "dof": v, "origin": origin})
    return included, excluded


def index(graph: KnowledgeGraph) -> dict:
    """Шаг 3 спеки: индекс Σ ln(DoF). Значение — только порядок сравнения, не величина."""
    included, excluded = calc_set(graph)
    if not included:
        return {"value": None, "terms": [], "excluded": excluded, "note": "множество calc пусто"}
    total = sum(math.log(t["dof"]) for t in included)
    return {"value": total, "terms": included, "excluded": excluded}


@dataclass
class Decision:
    chosen: Any                 # Path | None
    trace: dict


def evaluate(graph: KnowledgeGraph, paths: list, own_id: int = 0) -> Decision:
    """Шаги 3–4 спеки: индекс, NetDelta по каждому пути, выбор. Пишет протокол."""
    cur = index(graph)
    cur_v = cur["value"]

    candidates: list[dict] = []
    best = None
    best_net = None
    multiplier = None          # путь, создающий новую сущность (множитель DoF)

    for p in paths:
        step = p.steps[0]
        fam = action_family(step.action)
        proj = project(graph, step.ctrl, fam)
        net: Optional[float] = None
        why = proj.source
        if proj.known and cur_v is not None:
            delta = 0.0
            for kind, n in (proj.new_entities or {}).items():
                imp, cnt = impute(graph, kind)
                if imp and imp > 0:
                    delta += n * math.log(imp)
                else:
                    delta = None
                    why = f"появится {kind}, но его DoF неизвестен — считать нечем"
                    break
            if delta is not None:
                for kind, n in (proj.lost_entities or {}).items():
                    imp, _ = impute(graph, kind)
                    if imp and imp > 0:
                        delta -= n * math.log(imp)
                # Рост меню города — это рост DoF города, и он ИЗМЕРЕН (число разрешённых
                # позиций постройки). Без этого индекс слеп к тому, что даёт технология.
                k = int((proj.changes or {}).get("city_buildable_delta", 0) or 0)
                if k:
                    own = [e for e in graph.by_kind("city") if e.is_own]
                    vals = [d for d, _ in (dof_of(graph, e) for e in own) if d and d > 0]
                    if vals:
                        v = sorted(vals)[len(vals) // 2]
                        if v + k > 0:
                            delta += math.log(v + k) - math.log(v)
                            why = f"меню города: +{k} позиций (измерено)"
                net = delta - DT_DECLARED
        # множитель: путь, по наблюдённому эффекту создающий НОВУЮ сущность. Немедленный индекс
        # такое обычно не оценивает (юнит с 6 возможностями превращается в город с 2 — сумма
        # падает), но аксиома 6 велит предпочитать то, что умножает способность порождать новое.
        creates_entity = bool(proj.new_entities) if proj.known else False
        if creates_entity and multiplier is None:
            multiplier = p
        candidates.append({"path": p.to_dict(), "projection": proj.to_dict(),
                           "net_delta": net, "why": why, "multiplier": creates_entity})
        if net is not None and net > 0 and (best_net is None or net > best_net):
            best, best_net = p, net

    if best is not None:
        reason = f"наибольший NetDelta = {best_net:+.3f} > 0"
    elif multiplier is not None:
        best = multiplier
        reason = ("нет пути с NetDelta > 0 → берём множитель DoF: действие создаёт новую "
                  "сущность, а её будущий спектр немедленным индексом не оценивается (аксиома 6)")
    else:
        probes = [p for p in paths if p.kind == "проба"]
        best = probes[0] if probes else None
        reason = ("нет пути с NetDelta > 0 → ход тратится на прирост знания (аксиома 5)"
                  if best is not None else "нет ни полезного пути, ни пробы → закрыть ход")

    trace = {
        "index_current": cur_v,
        "calc_included": cur["terms"],
        "calc_excluded": cur["excluded"],
        "dt": DT_DECLARED,
        "candidates": candidates,
        "chosen": (best.to_dict() if best is not None else None),
        "reason": reason,
    }
    return Decision(chosen=best, trace=trace)