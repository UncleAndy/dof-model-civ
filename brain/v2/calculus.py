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
import os
import random
from dataclasses import dataclass
from typing import Any, Optional

from metrics.reversibility import classify_reversibility

from . import explore as explore_mod
from . import threat
from .families import action_family
from .horizon import (city_crowding_penalty, eta_of, production_gain, research_gain,
                      settler_spacing_factor, settler_uncrowding_gain, site_food_penalty)
from .horizon import tau as tau_window
from .knowledge import KnowledgeGraph
from .projection import project

#: виды сущностей, у которых есть собственный набор переходов
CALC_KINDS = ("unit", "city", "controller")

#: ΔT (энтропия переключения). Объявлено: 0.0 — прерывать пока нечего.
DT_DECLARED = 0.0

#: Минимум наблюдённых боёв, при котором удару можно давать цену. **Объявлено ДО данных**:
#: по одному бою исход оценивать нельзя — это была бы подгонка под случай.
MIN_FIGHTS = 5

#: Допуск разрешения ничьей (объявлен, структурное правило): если вариант с НЕИЗВЕСТНЫМ сроком
#: постройки проигрывает лучшему не более чем на эту долю цены, выбирается он — так закрывается
#: открытый вопрос (аксиома 5: незнание сужает путь), и почти без потери цены. Без этого варианта
#: с неизвестным сроком не выбирают НИКОГДА, и он навсегда остаётся неизвестным.
TIE_MARGIN = 0.05

#: Ничья разрешается СЛУЧАЙНО (решение Andy), но генератор случайности — с фиксированным seed,
#: иначе плечи сравнения перестают быть парными и прогоны не воспроизведутся.
_TIE_RNG = random.Random(int(os.environ.get("V2_TIE_SEED", "0")))


def _norm_actor(actor: Any) -> Any:
    """Актор к одному виду: число, если строка целиком цифровая (иначе ключи не совпадают)."""
    return int(actor) if isinstance(actor, str) and actor.isdigit() else actor


def _is_excluded(ctrl: str, actor: Any, action: str, exclude: set) -> bool:
    """Запрещено ли это действие: оно уже сделано в этом ходу или исчерпано его семейство."""
    a = _norm_actor(actor)
    return ((ctrl, a, action) in exclude
            or (ctrl, a, "family", action_family(action)) in exclude)


def _pick_max(rows: list[dict]) -> dict:
    """Максимум по `net_delta`; при ничьей — случайный выбор среди равных (seed фиксирован)."""
    top = max(r["net_delta"] for r in rows)
    tied = [r for r in rows if abs(r["net_delta"] - top) <= 1e-9]
    return _TIE_RNG.choice(tied) if len(tied) > 1 else tied[0]


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
                origin = "измерено" if e.is_own else "выведено (аналогия)"
                if e.is_own:
                    # §10.108: поселенец под своим городом дешевеет — множитель по близости.
                    fct, why = settler_spacing_factor(graph, e)
                    if fct < 1.0:
                        v = v * fct
                        origin = f"{origin}; {why}"
                return v, origin
    v = _family_dof(e)
    if v is not None:
        return v, "измерено"
    return None, "неизвестно"


def impute(graph: KnowledgeGraph, kind: str) -> tuple[Optional[float], int]:
    """Среднее по известным того же вида — как моделировать незнание (не нулём).

    Если ни одной сущности этого вида в графе НЕТ (типичный случай для города: пока агент своего не
    основал, городов нет вовсе), берём **измеренный DoF вида**, накопленный за прошлые партии в
    канале наблюдений. Это разрывает замкнутый круг «нет города → нет замера → нет цены → нет города»
    (найдено замером: все 601 кандидат `found_city` имели `net_delta: null`, §10.88).

    Для города срез — **размер 1** (новый город рождается размером 1); записи с пустым окном меню
    (0 переходов, загрязнение `PersistentCityProduction`) в канал не попадают вовсе.
    """
    vals = []
    for e in graph.by_kind(kind):
        v, _ = dof_of(graph, e)
        if v is not None:
            vals.append(v)
    if vals:
        vals.sort()
        return vals[len(vals) // 2], len(vals)
    measured = None
    if kind == "city":
        if os.environ.get("V2_NO_CITY_PRICE") == "1":
            # АБЛЯЦИЯ для парного сравнения (пункт 1 Andy): цена города выключена — тогда
            # `found_city` снова без числа, как было до правки В1. Нужна, чтобы вклад именно этой
            # правки измерялся на одних и тех же сидах, а не сравнивался с прошлыми прогонами.
            return None, 0
        # 1) ДОСТИЖИМОЕ значение своих городов (В1), 2) расчёт по измеренным частям, 3) прежний канал.
        own = (graph.observed_median("dof_city_reach", {"размер": 1})
               or graph.observed_median("dof_city_reach"))
        if own and own > 0:
            return float(own), 1
        f_own = (graph.observed_median("city_own_families", {"размер": 1})
                 or graph.observed_median("city_own_families"))
        n_build = graph.observed_median("city_size_buildable", {"размер": 1})
        types = [float(t.attrs.get("dof_families") or 0) for t in graph.by_kind("unit_type")]
        types = [v for v in types if v > 0]
        if f_own and n_build and types:
            # В1 при отсутствии своего города: свои семейства + разрешённые постройки × средняя
            # измеренная DoF типа. Все три части ИЗМЕРЕНЫ; среднее — по правилу «незнание ≠ ноль».
            est = float(f_own) + float(n_build) * (sum(types) / len(types))
            if est > 0:
                return est, 1
        measured = (graph.observed_median("dof_city", {"размер": 1})
                    or graph.observed_median("dof_city"))
    else:
        measured = graph.observed_median(f"dof_{kind}")
    if measured and measured > 0:
        return float(measured), 1
    return None, 0


def calc_set(graph: KnowledgeGraph, turn: Optional[int] = None) -> tuple[list[dict], list[dict]]:
    """Шаг 2 спеки: какие сущности входят в расчёт, какие исключены и почему."""
    if turn is None:
        turn = (graph.world or {}).get("ход")
    included: list[dict] = []
    excluded: list[dict] = []
    for kind in CALC_KINDS:
        for e in sorted(graph.by_kind(kind), key=lambda x: x.eid):
            v, origin = dof_of(graph, e)
            # ИСТОЧНИК КОЛЛАПСА: его возможности — НЕ наши (решения Andy, §10.33: для атакующего
            # знак был неверный — он прибавлял системе свои опции). Мирные чужие по-прежнему
            # плюсуются; исключается только тот, чьё нападение наблюдено.
            if not e.is_own and graph.is_collapse_source(e.eid, turn):
                excluded.append({"eid": e.eid,
                                 "why": "источник коллапса: его возможности не наши (нападение "
                                        "наблюдено)",
                                 "origin": origin,
                                 "под_ударом_do": v})
                continue
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


def knowledge_gain(graph: KnowledgeGraph, alts: list[str]) -> tuple[float, str]:
    """ЦЕНА НЕЗНАНИЯ: сколько стоит не знать срок постройки варианта.

    Объявлено (структурное правило, указание Andy): незнание параметра само по себе — стимул его
    выяснить, и постройка одного юнита ради этого выгодна. Величина берётся **из измерения**, а не
    назначается: это **размах ценностей вариантов, чей срок уже известен** (`max − min`). Смысл:
    решение под незнанием — пессимистичное (аксиома 5), а знание снимает пессимизм; размах
    показывает, сколько на этом можно выиграть, и служит верхней границей цены знания.

    Мера именно размах, а не «max − медиана»: измерено, что при двух известных вариантах медиана
    совпадает с максимумом, и цена знания обращалась в ноль всегда — стимул пропадал.

    При нулевом размахе (все известные варианты равны) знание не даёт НИЧЕГО — и не начисляется.
    """
    known: list[float] = []
    for a in alts or []:
        if action_family(a) != "produce":
            continue
        eta, src = eta_of(graph, str(a)[len("produce_"):])
        if eta is None or str(src).startswith("срок неизвестен"):
            continue                       # срок не известен — этот вариант не мерка
        g, _ = production_gain(graph, a)
        if g and g > 0:
            known.append(float(g))
    if len(known) < 2:
        return 0.0, "разброс ценностей не измерить (известных вариантов меньше двух)"
    known.sort()
    spread = known[-1] - known[0]
    if spread <= 0:
        return 0.0, "разброс ценностей нулевой — знание ничего не даёт"
    return spread, (f"цена незнания = размах известных ценностей "
                    f"({known[-1]:.3f} − {known[0]:.3f} = {spread:.3f}, n={len(known)})")


def _option_net(graph: KnowledgeGraph, cur_v, ctrl: str, action: str,
                actor: Optional[str] = None, depth: int = 1,
                kg: float = 0.0, kg_why: str = "") -> dict:
    """NetDelta одного конкретного действия (варианта семейства).

    ВАЖНО (измерено): цена угрозы и горизонтные выигрыши считаются по **измеренному состоянию**
    (расстояния, скорости, опубликованные сроки), а не по записи эффекта семейства. Поэтому они
    считаются ВНЕ ветки «эффект наблюдён»: иначе уход из-под удара получал `net = None` только
    потому, что семейство `goto` ещё не пробовалось, и агент выбирал пробу вместо защиты.
    """
    fam = action_family(action)
    tw, twwhy = tau_window(graph)
    # Окно угрозы — ОТДЕЛЬНАЯ величина (threat.STRIKE_TURNS), а не τ: измерено, что приорная
    # τ = 5.8 при v=3 покрывает ≈17 клеток и как признак угрозы ничего не различает.
    sw = threat.STRIKE_TURNS
    proj = project(graph, ctrl, fam)
    delta: Optional[float] = 0.0
    why = proj.source
    gained = False                      # был ли хоть один измеренный источник выигрыша
    unknown_eta = False                 # вариант постройки с НЕИЗВЕСТНЫМ сроком (ниже — почему)

    if proj.known and cur_v is not None:
        for kind, n in (proj.new_entities or {}).items():
            imp, _cnt = impute(graph, kind)
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
            k = float((proj.changes or {}).get("city_buildable_delta", 0) or 0)
            if k:
                own = [e for e in graph.by_kind("city") if e.is_own]
                vals = [d for d, _ in (dof_of(graph, e) for e in own) if d and d > 0]
                if vals:
                    v = sorted(vals)[len(vals) // 2]
                    if v + k > 0:
                        delta += math.log(v + k) - math.log(v)
                        why = f"меню города: {k:+.2f} позиций за действие (измерено)"
                        gained = True

    # --- выигрыши из измеренного состояния (не зависят от записи эффекта) ---
    if delta is not None:
        if fam == "research_tech":
            g_h, why_h = research_gain(graph, action)
            if g_h > 0:
                delta += g_h
                why = why_h
                gained = True
            elif why_h:
                why = why_h
        if fam == "produce":
            g_p, why_p = production_gain(graph, action, actor=str(actor) if actor is not None else None)
            # Ступень срока: если он ВЗЯТ СРЕДНИМ по измеренным (то есть сам неизвестен), вариант
            # помечается — при почти равной цене предпочтение отдаётся ему (см. TIE_MARGIN).
            _eta, _et_src = eta_of(graph, str(action)[len("produce_"):])
            if _eta is not None and str(_et_src).startswith("срок неизвестен"):
                unknown_eta = True
            if g_p > 0:
                delta += g_p
                why = why_p
                gained = True
                # НЕЗНАНИЕ КАК СТИМУЛ (указание Andy): если срок этого варианта неизвестен,
                # его постройка не только даёт сущность, но и УСТРАНЯЕТ незнание. Цена устранения
                # — измеренный разброс ценностей известных вариантов (см. `knowledge_gain`).
                if unknown_eta and kg > 0:
                    delta += kg
                    why = f"{why_p} | НЕЗНАНИЕ: срок неизвестен → +{kg:.3f} за устранение ({kg_why})"
            elif why_p:
                why = why_p
        h = (graph.effect_of(ctrl, fam) or {}).get("horizon") or {}
        grew = h.get("city_grew") or 0
        if grew > 0:
            sizes = sorted(e.attrs["size"] for e in graph.by_kind("city")
                           if e.is_own and isinstance(e.attrs.get("size"), int))
            if sizes:
                cur_size = sizes[len(sizes) // 2]
                v_now = graph.observed_median("city_size_buildable", {"размер": cur_size})
                v_next = graph.observed_median("city_size_buildable",
                                               {"размер": cur_size + grew})
                if v_now and v_next and v_next > v_now:
                    delta += math.log(v_next) - math.log(v_now)
                    why = (f"опыт: удержание {ctrl}/{fam} {h.get('ходов')} ход(ов) растит город "
                           f"на {grew}; переходов {v_now:g} → {v_next:g} (измерено)")
                    gained = True
        if actor is not None:
            if fam == "goto":
                g_m, why_m = threat.movement_gain(graph, ctrl, action, str(actor), dof_of, sw,
                                                  steps_count=depth)
                if g_m > 0:
                    delta += g_m
                    why = why_m
                    gained = True
                # ИССЛЕДОВАНИЕ (цель `explore`, §10.81): раскрытая карта — единственный способ
                # увидеть чужие сущности, а мирные чужие ПЛЮСУЮТСЯ к общему DoF. Цена — из
                # измеренного: клеток на ход × сущностей на клетку × ln(DoF обнаруженной).
                g_e, why_e = explore_mod.explore_gain(
                    graph, action, str(actor), dof_of,
                    lambda gg: impute(gg, "unit"))
                if g_e > 0:
                    delta += g_e
                    why = why_e
                    gained = True
                elif why_e and not g_m:
                    why = why_e
                # §10.108 п.3: уход поселенца ПРОЧЬ от города снимает штраф близости (рост ln(DoF)).
                _ux = graph.entity(f"unit:{actor}")
                _vx, _ox = dof_of(graph, _ux) if _ux is not None else (None, "")
                _xsize = int((graph.world or {}).get("xsize") or 0)
                if _vx and _vx > 0:
                    g_c, why_c = settler_uncrowding_gain(graph, str(actor), action, float(_vx),
                                                         _xsize)
                    if g_c > 0:
                        delta += g_c
                        why = f"{why_c}; {why}" if why and why != _ox else why_c
                        gained = True
            if fam == "attack":
                st = graph.fight_stats()
                if st["n"] < MIN_FIGHTS:
                    why = (f"удар по источнику коллапса: боёв наблюдено {st['n']} < {MIN_FIGHTS} "
                           f"— оценивать нечем (по одному бою цену не даём)")
                else:
                    pose = st["чужой_исчез"] / st["n"]
                    lose = st["наш_потерян"] / st["n"]
                    g_a, why_a = threat.strike_gain(graph, ctrl, action, str(actor), dof_of,
                                                    pose, lose, sw)
                    if why_a:
                        why = why_a
                    if g_a > 0:
                        delta += g_a
                        gained = True
            if fam == "build_city":
                g_f, why_f = threat.founding_risk(graph, action, str(actor), dof_of, impute, sw)
                if g_f < 0:
                    delta += g_f
                    why = why_f
                    gained = True
                # §10.108: ПЕРЕНАСЕЛЁННОСТЬ и ПЛОДОРОДИЕ участка — иначе агент ставил города
                # вплотную (замер: 2-й город всегда на мин. дистанции 2 от первого).
                g_cc, why_cc = city_crowding_penalty(graph, str(actor))
                if g_cc > 0:                       # штраф положительный — вычитаем
                    delta -= g_cc
                    why = f"{why_cc}; {why}" if why else why_cc
                    gained = True
                _imp_city, _n = impute(graph, "city")
                g_sf, why_sf = site_food_penalty(graph, str(actor), dof_city=_imp_city)
                if g_sf < 0:                       # штраф отрицательный — прибавляем
                    delta += g_sf
                    why = f"{why_sf}; {why}" if why else why_sf
                    gained = True

    if delta is None:
        net: Optional[float] = None
    elif proj.known or gained:
        net = delta - DT_DECLARED
    else:
        net = None                       # ни эффекта, ни измеренного выигрыша — неизвестно
    creates = bool(proj.new_entities) if proj.known else False
    return {"action": action, "net_delta": net, "why": why, "projection": proj.to_dict(),
            "multiplier": creates, "unknown_eta": unknown_eta}


def evaluate(graph: KnowledgeGraph, paths: list, own_id: int = 0,
             exclude: Optional[set] = None) -> Decision:
    """Шаги 3–4 спеки: индекс, NetDelta по каждому пути, выбор. Пишет протокол.

    Варианты внутри семейства выбирает **calculus**, а не генератор: берём вариант с наибольшим
    положительным NetDelta; если положительных нет — оставляем объявленный порядок (среди
    непобеждающих вариантов модель не ранжирует: это была бы оценка, а не расчёт).

    `exclude` — пути, которые запрещено повторять: агент передаёт прошлый выбор, когда состояние
    значимо не изменилось (иначе решение зацикливается, что и было измерено).
    """
    cur = index(graph)
    cur_v = cur["value"]
    exclude = exclude or set()
    _tw, _twwhy = tau_window(graph)
    _risk_price, _risk_detail = threat.risk_price(graph, dof_of, threat.STRIKE_TURNS)
    _risk = {"цена": round(_risk_price, 3), "под_ударом": _risk_detail,
             "окно_удара": threat.STRIKE_TURNS, "τ": round(_tw, 1)}

    candidates: list[dict] = []
    best = None
    best_net = None
    tied: list = []
    multiplier = None

    for p in paths:
        step = p.steps[0]
        alts = step.alternatives or [step.action]
        # Варианты, уже сделанные в этом ходу (или семейство которых исчерпано), выкидываем ДО
        # выбора: иначе один путь канала блокировался бы целиком из-за одного исчерпанного варианта.
        alts = [a for a in alts if not _is_excluded(step.ctrl, step.actor, a, exclude)]
        if not alts:
            candidates.append({"path": p.to_dict(), "projection": None, "net_delta": None,
                               "why": "исключён: все варианты уже использованы в этом ходу",
                               "multiplier": False, "исключён": True})
            continue
        kg, kg_why = (knowledge_gain(graph, alts) if step.ctrl == "city" else (0.0, ""))
        results = [_option_net(graph, cur_v, step.ctrl, a, actor=step.actor,
                               depth=len(p.steps), kg=kg, kg_why=kg_why)
                   for a in alts[:120]]
        positive = [r for r in results if r["net_delta"] is not None and r["net_delta"] > 0]
        # «ОСТАВИТЬ ТЕКУЩУЮ ПОСТРОЙКУ» — не действие, а БАЗА сравнения (§10.103). Мир не предлагает
        # уже начатую постройку как вариант, поэтому она не участвовала в выборе, и город менял
        # вариант каждый ход, не доводя ничего до конца. Смена оправдана только если даёт больше,
        # чем продолжение начатой постройки.
        if step.ctrl == "city":
            _ce = graph.entity(f"city:{step.actor}")
            _cur = _ce.attrs.get("стройка") if _ce is not None else None
            if _cur:
                _keep, _ = production_gain(graph, f"produce_{_cur}", actor=step.actor)
                if _keep > 0:
                    results = [r for r in results
                               if not (action_family(r["action"]) == "produce"
                                       and (r["net_delta"] or 0) <= _keep)]
                    positive = [r for r in results
                                if r["net_delta"] is not None and r["net_delta"] > 0]
                    if not results:
                        candidates.append({"path": p.to_dict(), "projection": None,
                                           "net_delta": None,
                                           "why": f"смена производства не выгоднее продолжения "
                                                  f"{_cur} ({_keep:+.3f}) — город продолжает стройку",
                                           "multiplier": False, "исключён": True})
                        continue
        pick = _pick_max(positive) if positive else results[0]
        if positive:
            # Объявленное правило разрешения ничьей: если вариант с НЕИЗВЕСТНЫМ сроком постройки
            # отстаёт от лучшего меньше чем на TIE_MARGIN, берём его — так открытый вопрос
            # закрывается за счёт хода, который всё равно был бы потрачен на постройку.
            best_r = _pick_max(positive)
            margin = abs(best_r["net_delta"]) * TIE_MARGIN
            close = [r for r in positive
                     if r.get("unknown_eta")
                     and best_r["net_delta"] - r["net_delta"] <= margin]
            if close:
                pick = close[0]
        # Исключение — последняя проверка (страховка): вариант мог стать исключённым после выбора.
        if _is_excluded(step.ctrl, step.actor, pick["action"], exclude):
            candidates.append({"path": p.to_dict(), "projection": None, "net_delta": None,
                               "why": "исключён: вариант уже использован в этом ходу",
                               "multiplier": False, "исключён": True})
            continue
        if pick["action"] != step.action:
            step.action = pick["action"]
            step.reversible = classify_reversibility(pick["action"])
            # Метка эффекта канала должна показывать РЕАЛЬНО выбранное семейство, а не
            # представителя по алфавиту: иначе протокол говорит «city_unwork», а выбрано «produce».
            if isinstance(p.effect, tuple) and len(p.effect) == 3 and p.effect[0] == "channel":
                p.effect = ("channel", p.effect[1], action_family(pick["action"]))
        net = pick["net_delta"]
        why = pick["why"]
        if pick["multiplier"] and multiplier is None:
            multiplier = p
        candidates.append({"path": p.to_dict(), "projection": pick["projection"],
                           "net_delta": net, "why": why, "multiplier": pick["multiplier"],
                           "вариантов_рассмотрено": len(results),
                           "лучший_вариант": pick["action"] if positive else None,
                           # Протокол Proof of Implementation: какие варианты рассматривались и с
                           # какой ценой — иначе «почему выбран этот» не проверить.
                           "варианты": [{"действие": r["action"], "net_delta": r["net_delta"],
                                         "срок_неизвестен": bool(r.get("unknown_eta"))}
                                        for r in sorted(results,
                                                        key=lambda x: (x["net_delta"] is None,
                                                                       -(x["net_delta"] or 0)))[:8]]})
        if net is not None and net > 0:
            if best_net is None or net > best_net + 1e-9:
                best, best_net, tied = p, net, [p]
            elif abs(net - best_net) <= 1e-9:
                tied.append(p)

    # Ничья по цене разрешается случайно (решение Andy), seed фиксирован — воспроизводимость.
    if len(tied) > 1:
        best = _TIE_RNG.choice(tied)

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

    for p in paths:
        p.irreversible = any(not s.reversible for s in p.steps)

    trace = {
        "index_current": cur_v,
        "calc_included": cur["terms"],
        "calc_excluded": cur["excluded"],
        "dt": DT_DECLARED,
        "риск": _risk,
        "candidates": candidates,
        "chosen": (best.to_dict() if best is not None else None),
        "reason": reason,
    }
    return Decision(chosen=best, trace=trace)