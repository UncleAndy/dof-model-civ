"""Наблюдение НАПАДЕНИЯ: чужая сущность становится «источником коллапса» только по факту.

РЕШЕНИЯ ANDY (приняты, §10.33/§10.34 — воспроизведены дословно):

1. Мирные чужие сущности ПЛЮСУЮТСЯ к общему DoF (как и работает).
2. Атака считается состоявшейся только если её видно НА ОТКРЫТЫХ клетках: «догадка из тумана
   нападением не считается».
3. Признак «источник коллапса» держится ВЕСЬ СРОК ПРОГНОЗА (горизонт), а не один ход.
   Горизонт — 20 ходов (`knowledge.COLLAPSE_HORIZON`).

ПОЭТОМУ до первого наблюдённого нападения цена риска ОТСУТСТВУЕТ (не «ноль», а «нечего
считать»): боеспособный сосед — ещё не нападение.

ЧТО СЧИТАЕТСЯ НАПАДЕНИЕМ (механизм, объявлен до данных):

* **наша сущность исчезла** между двумя полными срезами (юнит или город) — и её исчезновение
  НЕ объясняется нашим собственным измеренным действием (`build_city`, `join_city` — мир
  публикует, что они потребляют юнита);
* **или `health` нашей сущности упал** между срезами (её ударили, но не убили);
* И при этом на СМЕЖНОЙ клетке текущего среза виден чужой юнит. Видимость = раскрытая клетка
  (мир отдаёт только раскрытое), поэтому п.2 выполняется по построению.

Атрибуция НЕ выдумывается: если видимого соседа нет, факт записывается как «нападающий не
наблюдён» — без назначения виновного.
"""
from __future__ import annotations

import math
from typing import Optional

from . import sensors, threat
from .knowledge import KnowledgeGraph

#: Семейства НАШИХ действий, которые по измеренному эффекту мира потребляют своего юнита.
#: Их исчезновение нападением не считается (иначе основание города читалось бы как атака врага).
OWN_CONSUMES = ("build_city", "join_city")


def own_state(obs: dict, own_id: int) -> dict:
    """Полный срез нашего: юниты (позиция, здоровье) и города (позиция)."""
    st: dict = {"units": {}, "cities": {}}
    for u in sensors.own_actors(obs, own_id):
        st["units"][str(u.aid)] = {"x": u.x, "y": u.y,
                                   "health": (u.attrs or {}).get("health")}
    for c in sensors.own_cities(obs, own_id):
        st["cities"][str(c.cid)] = {"x": c.x, "y": c.y}
    return st


def _visible_foreign(obs: dict, own_id: int) -> list[dict]:
    """Чужие юниты, видимые в этом срезе: и с паспортом, и только по карте."""
    out = []
    for a in sensors.foreign_actors(obs, own_id):
        out.append({"eid": f"unit:{a.aid}", "owner": a.owner, "x": a.x, "y": a.y,
                    "name": a.type_name, "источник": "наблюдение:unit"})
    w = sensors.read_world(obs, own_id)
    uo = sensors._as_list(w.unit_owner)
    seen = {(u["owner"], u["x"], u["y"]) for u in out}
    for x, col in enumerate(uo):
        for y, o in enumerate(col if isinstance(col, (list, tuple)) else [col]):
            try:
                owner = int(o)
            except (TypeError, ValueError):
                continue
            if owner in (255, own_id) or (owner, x, y) in seen:
                continue
            out.append({"eid": f"unit:{owner}@{x},{y}", "owner": owner, "x": x, "y": y,
                        "name": None, "источник": "карта:unit_owner"})
    return out


def observe_slice(graph: KnowledgeGraph, obs: dict, own_id: int, turn: Optional[int],
                  prev: Optional[dict], last_choice: Optional[tuple] = None) -> tuple[list[dict], dict]:
    """Сравнить два полных среза и, если нападение НАБЛЮДЕНО, пометить источник коллапса.

    `last_choice` — (ctrl, actor, family) нашего последнего исполненного действия: если
    исчезнувший юнит — его актор и семейство в `OWN_CONSUMES`, нападения не было.
    Возвращает (события, новое состояние среза).
    """
    now = own_state(obs, own_id)
    events: list[dict] = []
    if prev is None or turn is None:
        return events, now
    # Ход 1 — начало партии: сравнивать не с чем. Без этой проверки срез ПРОШЛОЙ партии
    # сравнивался с первой партией новой, и наш прежний город читался как «потерян без
    # нападающего» (измерено: два таких ложных события на ходу 1 в прогоне long4).
    if int(turn) <= 1:
        return events, now

    foreign = _visible_foreign(obs, own_id)
    xsize = int((graph.world or {}).get("xsize") or 0)
    consumed = None
    if last_choice and len(last_choice) >= 3 and last_choice[2] in OWN_CONSUMES:
        consumed = {"actor": str(last_choice[1]), "family": last_choice[2]}

    victims: list[dict] = []
    for uid, old in (prev.get("units") or {}).items():
        new = (now["units"] or {}).get(uid)
        if new is None:
            if consumed is not None and consumed["actor"] == uid:
                continue                       # объяснено нашим же действием (измерено)
            victims.append({"вид": "юнит", "кто": uid, "x": old.get("x"), "y": old.get("y"),
                            "как": "потерян"})
        else:
            h0, h1 = old.get("health"), new.get("health")
            if isinstance(h0, int) and isinstance(h1, int) and h1 < h0:
                victims.append({"вид": "юнит", "кто": uid, "x": new.get("x"), "y": new.get("y"),
                                "как": f"ранен ({h0} → {h1})"})
    for cid, old in (prev.get("cities") or {}).items():
        if (now["cities"] or {}).get(cid) is None:
            victims.append({"вид": "город", "кто": cid, "x": old.get("x"), "y": old.get("y"),
                            "как": "потерян"})

    for v in victims:
        if v.get("x") is None or v.get("y") is None:
            continue
        adj = [f for f in foreign
               if threat.cheb(v["x"], v["y"], f["x"], f["y"], xsize) <= 1]
        if not adj:
            events.append({**v, "нападающий": None,
                           "вывод": "нападающий не наблюдён — виновный не назначается "
                                    "(догадка из тумана нападением не считается)"})
            graph.note_observation("нападение", {"ход": turn, "вид": v["вид"],
                                                 "как": v["как"], "нападающий": None})
            continue
        for f in adj:
            why = (f"нападение наблюдено: наш {v['вид']} {v['как']} на "
                   f"({v['x']},{v['y']}), чужой {f['eid']} стоял вплотную")
            graph.mark_collapse_source(f["eid"], turn, f.get("owner"), why)
            graph.note_observation("нападение", {"ход": turn, "вид": v["вид"], "как": v["как"],
                                                 "нападающий": f["eid"], "владелец": f.get("owner")})
            if f.get("owner") is not None:
                graph.note_observation("владелец_нападал", {"владелец": f["owner"], "ход": turn})
            events.append({**v, "нападающий": f["eid"], "владелец": f.get("owner"),
                           "вывод": why})
    return events, now