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
import os
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
#: §10.111: доля полной цены угрозы для «ПОТЕНЦИАЛЬНОГО источника» (чужой на нашей территории).
#: Задано Andy: не менее 0.8, т.к. нападение возможно при любом вторжении. Это скидка, не полная
#: цена: полная цена (источник коллапса) остаётся −ln(DoF города) при наблюдённой атаке.
POTENTIAL_FACTOR = 0.8
#: Абляция (§10.111): V2_NO_POTENTIAL=1 выключает «потенциальный источник» (арм без механизма).
_POTENTIAL_ENABLED = os.environ.get("V2_NO_POTENTIAL") != "1"


def offset_of(action: str) -> Optional[tuple[int, int]]:
    """Смещение действия по измеренной таблице dir8 — для `goto_N` И `attack_N`.

    Измерено: `attack_N` (`ActAttack(focus, dir8)`, `mapstep`) — та же геометрия, что у `goto_N`.
    """
    name = str(action)
    if "_" not in name:
        return None
    head, _, tail = name.rpartition("_")
    if head not in ("goto", "attack") or not tail.isdigit():
        return None
    return DIR8_MEASURED.get(f"goto_{tail}")


def cheb(ax: int, ay: int, bx: int, by: int, xsize: int) -> int:
    """Расстояние Чебышёва с замыканием X (карта-цилиндр, wrap_id=1)."""
    dx = abs(ax - bx)
    if xsize:
        dx = min(dx, xsize - dx)
    return max(dx, abs(ay - by))


def attack_of(graph: KnowledgeGraph, e) -> tuple[Optional[float], str]:
    """Атака чужой сущности: измеренная, если мир отдал паспорт; иначе — средняя по известным.

    ИЗМЕРЕНО: секция `unit` содержит только своих, а чужой виден лишь через `map.unit_owner`,
    без паспорта. Тогда атака неизвестна, и по правилу «неизвестное — средним по известным, не
    нулём» берётся средняя по известным типам; если и типов ещё нет — угроза не считается
    (нечем), но и не «ноль»: возвращается `None` с причиной.
    """
    a = e.attrs.get("type_attack_strength")
    if isinstance(a, (int, float)):
        return float(a), "измерено (паспорт типа)"
    mean_a, n = graph.mean_attack()
    if mean_a is None:
        return None, f"неизвестна и известных типов нет (n={n})"
    return mean_a, f"выведено: среднее по {n} известным типам (незнание ≠ ноль)"


def threats(graph: KnowledgeGraph, turn: Optional[int] = None) -> list[dict]:
    """T1: угрозы — ТОЛЬКО сущности, чьё нападение НАБЛЮДЕНО (решения Andy, §10.33/§10.34).

    Мирный чужой угрозой не считается: он обычная сущность со своим DoF и ПЛЮСУЕТСЯ к общему
    DoF. Близость боеспособного соседа нападением не является — «догадка из тумана нападением
    не считается». Поэтому до первого наблюдённого нападения список угроз пуст, и цена риска
    равна нулю не потому, что опасности нет, а потому что нападения ещё не было.

    Позиция источника берётся только если он виден в ТЕКУЩЕМ наблюдении: иначе сущность остаётся
    источником (флаг держится горизонт), но без устаревших координат.
    """
    seen_at = graph.observations
    if turn is None:
        turn = (graph.world or {}).get("ход")
    out = []
    for eid in graph.collapse_sources(turn):
        e = graph.entity(eid)
        if e is None or e.is_own or e.attrs.get("x") is None:
            continue
        if e.attrs.get("виден_наблюдение") not in (None, seen_at):
            continue                    # источник известен, но сейчас не виден
        a, origin = attack_of(graph, e)
        if a is None or a <= 0:
            continue
        info = graph.collapse_sources(turn).get(eid) or {}
        out.append({"eid": e.eid, "attack": float(a), "x": e.attrs["x"], "y": e.attrs["y"],
                    "move_rate": e.attrs.get("type_move_rate") or 1,
                    "происхождение_атаки": origin,
                    "источник_коллапса": True,
                    "почему": info.get("почему"), "с_хода": info.get("с_хода"),
                    "владелец": info.get("владелец")})
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


def source_price(graph: KnowledgeGraph, src_eid: str, dof_of,
                 tau: float = STRIKE_TURNS) -> tuple[float, list[str]]:
    """Сколько риска держит ИМЕННО этот источник: сумма ln(DoF) наших сущностей под его ударом.

    Это цена, которая исчезнет, если источник снять. Считается по измеренным расстояниям и DoF.
    """
    price = 0.0
    who: list[str] = []
    for eid, info in exposure(graph, tau).items():
        if info.get("угроза") != src_eid:
            continue
        e = graph.entity(eid)
        if e is None:
            continue
        v, _origin = dof_of(graph, e)
        if v and v > 0:
            price += math.log(v)
            who.append(eid)
    return price, who


def strike_gain(graph: KnowledgeGraph, ctrl: str, action: str, actor: str, dof_of,
                pose: float, lose: float, tau: float = STRIKE_TURNS) -> tuple[float, str]:
    """Цена удара по источнику коллапса — по ИЗМЕРЕННЫМ исходам наших боёв.

    `pose` — доля боёв, где чужой исчез; `lose` — доля боёв, где потерян наш юнит (обе дроби
    измерены, а не назначены). Цена удара = `pose` × (риск, который держит источник)
    − `lose` × ln(DoF нашего юнита). Если направления не видно или источника рядом нет —
    удара нет, и это не «ноль», а «нечего считать».
    """
    if ctrl != "unit":
        return 0.0, ""
    off = offset_of(action)
    if off is None:
        return 0.0, ""
    e = graph.entity(f"unit:{actor}")
    if e is None or e.attrs.get("x") is None:
        return 0.0, ""
    xsize = int((graph.world or {}).get("xsize") or 0)
    tx = (e.attrs["x"] + off[0]) % xsize if xsize else e.attrs["x"] + off[0]
    ty = e.attrs["y"] + off[1]
    src = None
    for t in threats(graph):
        if t["x"] == tx and t["y"] == ty:
            src = t
            break
    if src is None:
        return 0.0, ""
    held, who = source_price(graph, src["eid"], dof_of, tau)
    v, _ = dof_of(graph, e)
    if not v or v <= 0:
        return 0.0, (f"{action}: ударить можно, но DoF нашего юнита неизвестен — считать нечем")
    gain = pose * held - lose * math.log(v)
    why = (f"{action}: удар по источнику {src['eid']} — по измеренным боям: чужой исчезал в "
           f"{pose:.2f} случаев, наш юнит терялся в {lose:.2f}; риск источника "
           f"{held:+.3f} ({len(who)} сущностей), цена нашей потери {math.log(v):.3f} "
           f"→ {gain:+.3f}")
    return gain, why


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


def own_territory(graph: KnowledgeGraph) -> set:
    """§10.111: наша территория из графа (клетки `tile_owner == наш` ∪ радиусы наших городов)."""
    raw = (graph.world or {}).get("наша_территория") or []
    out = set()
    for it in raw:
        if isinstance(it, (list, tuple)) and len(it) == 2:
            out.add((int(it[0]), int(it[1])))
    return out


def potential_sources(graph: KnowledgeGraph) -> list[dict]:
    """§10.111: чужие юниты, стоящие на НАШЕЙ территории (наблюдённые, не догадка)."""
    if not _POTENTIAL_ENABLED:
        return []
    terr = own_territory(graph)
    if not terr:
        return []
    out: list[dict] = []
    for e in graph.by_kind("unit"):
        if e.is_own:
            continue
        x, y = e.attrs.get("x"), e.attrs.get("y")
        if x is None:
            continue
        if (int(x), int(y)) in terr:
            out.append({"eid": e.eid, "owner": e.owner, "x": int(x), "y": int(y)})
    return out


def potential_price(graph: KnowledgeGraph, dof_of) -> tuple[float, str]:
    """§10.111: цена «потенциального источника» = POTENTIAL_FACTOR × ln(DoF нарушенного города).

    Берём МАКСИМУМ по своим городам (а не сумму): вторжения у одного города — одна условная потеря,
    а не «складчина». Полная цена (источник коллапса) при наблюдённой атаке — отдельно (−ln DoF)."""
    srcs = potential_sources(graph)
    if not srcs:
        return 0.0, ""
    xsize = int((graph.world or {}).get("xsize") or 0)
    own_cities = [e for e in graph.by_kind("city")
                  if e.is_own and e.attrs.get("x") is not None]
    if not own_cities:
        return 0.0, ""
    best, who = 0.0, None
    for s in srcs:
        c = min(own_cities, key=lambda cc: cheb(cc.attrs["x"], cc.attrs["y"],
                                                s["x"], s["y"], xsize))
        v, _ = dof_of(graph, c)
        if not v or v <= 0:
            continue
        p = POTENTIAL_FACTOR * math.log(v)
        if p > best:
            best, who = p, c.eid
    if best <= 0:
        return 0.0, ""
    return best, (f"§10.111: чужой на нашей территории → условная угроза "
                  f"{POTENTIAL_FACTOR}×ln(DoF {who}) = {best:.2f}")


def displace_gain(graph: KnowledgeGraph, action: str, actor: str, dof_of) -> tuple[float, str]:
    """§10.111: выигрыш за шаг, ставящий НАШ ВОЕННЫЙ юнит вплотную к нарушителю.

    Блокировка/вытеснение: если после хода наш юнит (attack > 0) встаёт вплотную (Cheb ≤ 1) к чужому,
    стоящему на нашей территории, — условная угроза снимается. Выигрыш = её цена (не сумма шагов)."""
    e = graph.entity(f"unit:{actor}")
    if e is None or e.attrs.get("x") is None:
        return 0.0, ""
    atk = e.attrs.get("type_attack_strength")
    if not isinstance(atk, (int, float)) or atk <= 0:
        return 0.0, ""
    off = offset_of(action)
    if off is None or str(action).startswith("attack"):
        return 0.0, ""
    xsize = int((graph.world or {}).get("xsize") or 0)
    nx = ((e.attrs["x"] + off[0]) % xsize) if xsize else e.attrs["x"] + off[0]
    ny = e.attrs["y"] + off[1]
    srcs = potential_sources(graph)
    if not srcs:
        return 0.0, ""
    for s in srcs:
        before = cheb(e.attrs["x"], e.attrs["y"], s["x"], s["y"], xsize)
        after = cheb(nx, ny, s["x"], s["y"], xsize)
        if before > 1 and after <= 1:
            price, why = potential_price(graph, dof_of)
            if price > 0:
                return price, (f"{action}: встаём вплотную к {s['eid']} на нашей территории — "
                               f"вытесняем нарушителя; {why}")
    return 0.0, ""


def cover_gain(graph: KnowledgeGraph, action: str, actor: str, dof_of,
               steps_count: int = 1) -> tuple[float, str]:
    """§10.113: ПРИКРЫТИЕ ГОРОДА — военный юнит идёт в город/вплотную, когда рядом чужой.

    Мотив: чужая сущность у города делает город условно уязвимым (цена — как у «потенциального
    источника»). Оценивается КОНЕЦ хода (после `steps_count` шагов в этом направлении — так же,
    как уход из-под удара, `movement_gain`): шаг, чей конец встаёт вплотную к городу, закрывает
    условность. Поэтому юнит, стоящий ПООДАЛЬ (в пределах одного плана, H=3), получает мотив ИДТИ
    к городу, а не только «стоять рядом, если уже повезло».

    Сколько защитников нужно: число чужих в радиусе города, не меньше одного — каждому нарушителю
    свой защитник. Это не подобранная константа, а прямое следствие правила «один закрывает одного».
    """
    e = graph.entity(f"unit:{actor}")
    if e is None or e.attrs.get("x") is None:
        return 0.0, ""
    atk = e.attrs.get("type_attack_strength")
    if not isinstance(atk, (int, float)) or atk <= 0:
        return 0.0, ""
    off = offset_of(action)
    if off is None or str(action).startswith("attack"):
        return 0.0, ""
    xsize = int((graph.world or {}).get("xsize") or 0)
    # Путь по направлению: позиции после каждого шага плана. Засчитываем, если ХОТЬ ОДНА из них
    # вплотную к городу. Так верно и для юнита в 2–3 шагах (дойдёт), и для уже стоящего рядом
    # (шаг, который оставляет его у города, тоже прикрывает; шаг ПРОЧЬ — нет).
    path_pos: list[tuple[int, int]] = []
    nx, ny = e.attrs["x"], e.attrs["y"]
    for _ in range(max(1, steps_count)):
        nx = (nx + off[0]) % xsize if xsize else nx + off[0]
        ny = ny + off[1]
        path_pos.append((nx, ny))
    own_cities = [c for c in graph.by_kind("city")
                  if c.is_own and c.attrs.get("x") is not None]
    if not own_cities:
        return 0.0, ""
    own_mil = [u for u in graph.by_kind("unit")
               if u.is_own and u.attrs.get("x") is not None
               and isinstance(u.attrs.get("type_attack_strength"), (int, float))
               and u.attrs["type_attack_strength"] > 0]

    def _uid(u) -> int:
        tail = u.eid.split(":")[-1]
        return int(tail) if tail.isdigit() else 0

    best_gain, best_why = 0.0, ""
    for c in own_cities:
        if not any(cheb(c.attrs["x"], c.attrs["y"], px, py, xsize) <= 1
                   for px, py in path_pos):
            continue                # ни один шаг плана не ставит юнит вплотную к этому городу
        rsq = (c.attrs or {}).get("city_radius_sq")
        radius = int(math.isqrt(int(rsq))) if isinstance(rsq, (int, float)) and rsq >= 0 else 4
        foes_near = [f for f in graph.by_kind("unit")
                     if (not f.is_own) and f.attrs.get("x") is not None
                     and cheb(f.attrs["x"], f.attrs["y"], c.attrs["x"], c.attrs["y"], xsize)
                     <= radius]
        if not foes_near:
            continue                # у этого города чужих рядом нет — прикрывать не от кого
        need = max(1, len(foes_near))   # одному нарушителю — один защитник
        # ОПРЕДЕЛЁННЫЙ состав защитников: младшие по номеру занимают места первыми. Так «кто
        # остаётся» не решается гонкой (иначе два защитника, видя друг друга, уходили оба).
        adj = [u for u in own_mil
               if cheb(u.attrs["x"], u.attrs["y"], c.attrs["x"], c.attrs["y"], xsize) <= 1]
        adj.sort(key=_uid)
        designated = {u.eid for u in adj[:need]}
        if not (e.eid in designated or len(adj) < need):
            continue                # места заняты, а я не назначен — свободен для других целей
        v, _ = dof_of(graph, c)
        if not v or v <= 0:
            continue
        g = POTENTIAL_FACTOR * math.log(v)
        if g > best_gain:
            best_gain = g
            best_why = (f"{action}: прикрываем {c.eid} — рядом чужой ({foes_near[0].eid}), "
                        f"защитников {len(adj)}/{need}; снимаем условную угрозу "
                        f"{POTENTIAL_FACTOR}×ln(DoF)={g:.2f}")
    return best_gain, best_why


def hold_set(graph: KnowledgeGraph) -> set:
    """Дежурные защитники угрожаемых городов: держат позицию (не бегут, не сближаются).

    Почему (измерено): город уязвим, пока рядом чужой и нет защитника; уход оголяет город,
    а DoF города (множитель) много больше DoF одного юнита. Состав детерминированный:
    младшие по номеру, по числу чужих в радиусе города. Структурное решение, не подгонка.
    """
    xsize = int((graph.world or {}).get("xsize") or 0)
    own_mil = [u for u in graph.by_kind("unit")
               if u.is_own and u.attrs.get("x") is not None
               and isinstance(u.attrs.get("type_attack_strength"), (int, float))
               and u.attrs["type_attack_strength"] > 0]
    foes = [f for f in graph.by_kind("unit")
            if (not f.is_own) and f.attrs.get("x") is not None]
    hold: set = set()
    for c in [e for e in graph.by_kind("city") if e.is_own and e.attrs.get("x") is not None]:
        rsq = (c.attrs or {}).get("city_radius_sq")
        radius = int(math.isqrt(int(rsq))) if isinstance(rsq, (int, float)) and rsq >= 0 else 4
        foes_near = [f for f in foes
                     if cheb(f.attrs["x"], f.attrs["y"], c.attrs["x"], c.attrs["y"], xsize) <= radius]
        if not foes_near:
            continue
        need = max(1, len(foes_near))
        adj = [u for u in own_mil
               if cheb(u.attrs["x"], u.attrs["y"], c.attrs["x"], c.attrs["y"], xsize) <= 1]
        adj.sort(key=lambda u: (int(u.eid.split(":")[1]) if u.eid.split(":")[1].isdigit() else 0))
        hold.update(u.eid for u in adj[:need])
    return hold


def intercept_gain(graph: KnowledgeGraph, action: str, actor: str, dof_of,
                    steps_count: int = 1) -> tuple[float, str]:
    """§10.115: СБЛИЖЕНИЕ с объявленным источником коллапса — чтобы встать вплотную и ударить.

    Только против ВИДИМОГО источника (§10.33/§10.34 — «догадка из тумана нападением не
    считается») и только пока наш военный НЕ вплотную: иначе цена совпала бы с ценой удара
    (§10.114) и агент «завис» бы рядом вместо боя. Дежурные защитники (`hold_set`) не сближаются:
    их уход оголил бы город. Цена шага — риск, который держит источник (`source_price`), без
    новых коэффициентов.
    """
    e = graph.entity(f"unit:{actor}")
    if e is None or e.attrs.get("x") is None:
        return 0.0, ""
    atk = e.attrs.get("type_attack_strength")
    if not isinstance(atk, (int, float)) or atk <= 0:
        return 0.0, ""
    off = offset_of(action)
    if off is None or str(action).startswith("attack"):
        return 0.0, ""
    if e.eid in hold_set(graph):
        return 0.0, ""
    xsize = int((graph.world or {}).get("xsize") or 0)
    pts = []
    nx, ny = e.attrs["x"], e.attrs["y"]
    for _ in range(max(1, steps_count)):
        nx = (nx + off[0]) % xsize if xsize else nx + off[0]
        ny = ny + off[1]
        pts.append((nx, ny))
    best_gain, best_why = 0.0, ""
    for src in threats(graph):
        if cheb(e.attrs["x"], e.attrs["y"], src["x"], src["y"], xsize) <= 1:
            continue                       # уже вплотную — это дело удара (§10.114), не сближения
        if not any(cheb(px, py, src["x"], src["y"], xsize) <= 1 for px, py in pts):
            continue                       # план не доводит вплотную к источнику
        held, who = source_price(graph, src["eid"], dof_of)
        if held > best_gain:
            best_gain = held
            best_why = (f"{action}: сближаемся с источником коллапса {src['eid']} "
                        f"(вплотную за ≤{max(1, steps_count)} шаг.) — снимаем риск {held:.2f}")
    return best_gain, best_why


def defense_gain(graph: KnowledgeGraph, ctrl: str, action: str, actor: str, dof_of,
                 radius: float = 2.0) -> tuple[float, str]:
    """§10.114: ОТПОР — бьём ТОЛЬКО объявленный источник коллапса (нападение наблюдено).

    §10.33/§10.34: мирные чужие — не угроза, их вклад идёт в общий DoF; вторжение не есть источник
    коллапса. Удар возможен лишь против того, чьё нападение УЖЕ наблюдено. Нужно, чтобы бой шёл
    при нападении, даже когда исход боёв ещё не накоплен (нет статистики для `strike_gain`).
    """
    if ctrl != "unit":
        return 0.0, ""
    if action_family(action) != "attack":
        return 0.0, ""
    off = offset_of(action)
    if off is None:
        return 0.0, ""
    e = graph.entity(f"unit:{actor}")
    if e is None or e.attrs.get("x") is None:
        return 0.0, ""
    atk = e.attrs.get("type_attack_strength")
    if not isinstance(atk, (int, float)) or atk <= 0:
        return 0.0, ""
    xsize = int((graph.world or {}).get("xsize") or 0)
    tx = ((e.attrs["x"] + off[0]) % xsize) if xsize else e.attrs["x"] + off[0]
    ty = e.attrs["y"] + off[1]
    own_cities = [c for c in graph.by_kind("city")
                  if c.is_own and c.attrs.get("x") is not None]
    c = None
    if own_cities:
        c = min(own_cities, key=lambda cc: cheb(cc.attrs["x"], cc.attrs["y"], tx, ty, xsize))
        if cheb(c.attrs["x"], c.attrs["y"], tx, ty, xsize) > radius:
            c = None
    src = next((t for t in threats(graph) if t["x"] == tx and t["y"] == ty), None)
    if src is not None:
        # Полный риск, который держит ИМЕННО этот источник (сумма ln(DoF) всех наших сущностей
        # под его ударом) — снятие источника убирает ВЕСЬ этот риск, а не одну сущность.
        held, who = source_price(graph, src["eid"], dof_of)
        if held > 0:
            where = f" у {c.eid}" if c is not None else ""
            return held, (f"{action}: ОТПОР — бьём источник коллапса {src['eid']}{where}; "
                          f"снимаем риск {held:.2f} ({len(who)} наших сущностей)")
        if c is not None:
            v, _ = dof_of(graph, c)
            if v and v > 0:
                return math.log(v), (f"{action}: ОТПОР — бьём источник коллапса {src['eid']} у "
                                     f"{c.eid}; снимаем угрозу ln(DoF)={math.log(v):.2f}")
        v, _ = dof_of(graph, e)
        if v and v > 0:
            return math.log(v), (f"{action}: ОТПОР — бьём источник коллапса {src['eid']}; "
                                 f"снимаем угрозу нашему юниту ln(DoF)={math.log(v):.2f}")
        return 0.0, ""
    # §10.33/§10.34: по МИРНОМУ нарушителю удара нет — его только вытесняют (блокировка, goto).
    return 0.0, ""