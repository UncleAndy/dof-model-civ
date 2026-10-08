"""§13.93: у нападающего есть узел — проверки П1-П5 (объявлены до этих данных).

Удар делается из НАСТОЯЩЕГО захвата: меню, дипломатия и карта — мира, меняются ровно
два поля, которые и составляют удар, — здоровье жертвы и чужой владелец на смежной
клетке. Так проверяется весь путь, а не выдуманный случай.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.spec.calculus_core import DOFCalculusCore    # noqa: E402
from env import entity_extractor as E                   # noqa: E402
from env import spec_graph as G                         # noqa: E402
from env import spec_obs as SO                          # noqa: E402

OK = 0
BAD = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ok   {name}" + (f" | {detail}" if detail else ""))
    else:
        BAD += 1
        print(f"  ПЛОХО {name}" + (f" | {detail}" if detail else ""))


def _map(cells: dict) -> list:
    grid = [[255] * 4 for _ in range(4)]
    for (x, y), own in cells.items():
        grid[y][x] = own
    return grid


def syn(our_health: int, foe: int | None = None) -> dict:
    """Синтетическая пара из §13.91: наш рабочий (потолок 10) и чужая сила 3 в `dipl`."""
    return {
        "unit": {"5": {"owner": 0, "x": 1, "y": 1, "health": our_health,
                       "type_hp": 10, "type_rule_name": "Workers",
                       "moves_left": 1, "max_moves": 1}},
        "city": {"121": {"owner": 0, "x": 2, "y": 2}},
        "dipl": {"0": {"diplomatic_state": 5}, "3": {"diplomatic_state": 5}},
        "map": {"unit_owner": _map({} if foe is None else {(1, 2): foe})},
    }


def poisoned(prev: dict, cur: dict):
    """Сделать из пары настоящих срезов наблюдённый удар: health падает, чужой виден рядом."""
    prev, cur = copy.deepcopy(prev), copy.deepcopy(cur)
    units = cur.get("unit") or {}
    victim = None
    for k, v in sorted(units.items()):
        if isinstance(v, dict) and int(v.get("owner", 0) or 0) == 0 and v.get("health"):
            victim = (k, v)
            break
    if victim is None:
        return None
    vid, rec = victim
    x, y = int(rec.get("x") or 0), int(rec.get("y") or 0)
    grid = (cur.get("map") or {}).get("unit_owner")
    if not isinstance(grid, list) or not grid or not isinstance(grid[0], list):
        return None
    rec["health"] = 2                       # удар почти насмерть: порог §13.92 пройден
    gy, gx = min(max(y, 0), len(grid) - 1), min(max(x, 0), len(grid[0]) - 1)
    cells = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = gx + dx, gy + dy
        if 0 <= ny < len(grid) and 0 <= nx < len(grid[ny]):
            cells.append((ny, nx, grid[ny][nx]))
    free = [c for c in cells if c[2] == 255]
    pick = (free or cells)[0]
    grid[pick[0]][pick[1]] = 3
    side = "свободная" if pick[2] == 255 else f"занятая ({pick[2]})"
    return prev, cur, f"unit_{vid}", side


def main() -> None:
    print("объявлено заранее: П1 метка ложится на узел силы diplomacy_3; П2 акт удара в графе "
          "ведёт от узла силы к нашей сущности с измеренной величиной; П3 при ударе, доводящем "
          "цель до нуля, свидетель подтверждает метку и узел уходит из набора, без акта — "
          "остаётся; П4 наши узлы не помечаются; П5 на захвате без наблюдённого удара "
          "изменений нет")

    raw = json.loads((ROOT / "tests" / "fixtures" / "real_obs_01.json").read_text("utf-8"))
    rows = [s for s in raw if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    prev_step, cur_step = rows[-2], rows[-1]
    pois = poisoned(prev_step["observation"], cur_step["observation"])
    if pois is None:
        print("захват не дал жертвы для удара — проверка невозможна")
        sys.exit(2)
    prev_obs, cur_obs, victim_id, side = pois
    print(f"  удар: {victim_id}, чужой владелец 3 поставлен на {side} клетку")

    extr = E.GameStateExtractor()
    extr.extract(prev_obs, prev_step.get("info") or {}, prev_step.get("turn", 1))
    m = SO.measure_step(cur_obs, cur_step.get("info") or {}, cur_step.get("turn", 2),
                        extr, prev_obs=prev_obs, my_player_id=0)
    ev = getattr(extr, "last_attack_event", {}) or {}
    acts = ev.get("strikes") or []
    hosts = ev.get("label_hosts") or []
    matrix = getattr(m["state"], "state", m["state"])
    ents = getattr(matrix, "entities", None) or m["state"].entities
    print(f"  событие: attacked={ev.get('attacked')} жертвы={ev.get('victims')} "
          f"нападавшие={ev.get('attackers')}")
    acts_line = [(a.get("source"), a.get("target"), round(a.get("delta") or 0, 4))
                 for a in acts]
    print(f"  сущностей {len(ents)}; акты {acts_line}")
    print(f"  размещение метки: {hosts}")

    # ── П1
    node = ents.get("diplomacy_3")
    check("П1 метка ложится на узел силы diplomacy_3, который есть в состоянии",
          any(str(h.get("узел")) == "diplomacy_3" for h in hosts)
          and node is not None and bool(getattr(node, "is_collapse_source", False)),
          f"узел есть {node is not None}, помечен "
          f"{bool(getattr(node, 'is_collapse_source', False))}")

    # ── П2: акт в графе, построенном тем же способом, что в адаптере
    gr = G.world_graph(m["vectors"], m["fields"], m["dof"], catalogue=m["catalogue"],
                       known_techs=m["known_techs"], raw_menus=m["raw_menus"], strikes=acts)
    in_graph = [a for a in gr.acts if a.id.startswith("strike:")]
    graph_line = [(a.source, a.target, round(a.effect.get(a.target, 0.0), 4), a.category)
                  for a in in_graph]
    print(f"  актов в графе {len(gr.acts)}, из них ударов {len(in_graph)}: {graph_line}")
    check("П2 акт удара в графе ведёт от узла силы к нашей сущности с измеренной величиной",
          len(in_graph) == 1 and in_graph[0].source == "diplomacy_3"
          and in_graph[0].target == victim_id
          and in_graph[0].effect.get(victim_id, 0.0) < 0.0
          and in_graph[0].category == "observed_attack",
          f"узлов в графе {len(gr.entities)}")

    # ── П3: свидетель
    # На захвате жертва БОГАТА (DoF 0.98): удар до нуля её не доводит, и свидетель не
    # срабатывает — это измеренный факт, он печатается. Порог — свойство линзы жертвы
    # (§13.92), поэтому переключение проверяется на БЕДНОЙ жертве (§13.91): там DoF мал, и
    # удар почти насмерть доводит цель до нуля.
    core = DOFCalculusCore()
    st = G.state_with_measured_dof(m["state"], m["dof"])
    members = core.calc_members(st, G.observation_context(gr, m["dof"]))
    gr_no = G.world_graph(m["vectors"], m["fields"], m["dof"], catalogue=m["catalogue"],
                          known_techs=m["known_techs"], raw_menus=m["raw_menus"], strikes=())
    members_no = core.calc_members(st, G.observation_context(gr_no, m["dof"]))
    dof_v = float(m["dof"].get(victim_id, 0.0))
    delta = in_graph[0].effect.get(victim_id, 0.0) if in_graph else 0.0
    print(f"  [захват] DoF {victim_id} {dof_v:.4f} + величина {delta:+.4f} = "
          f"{dof_v + delta:+.4f} — удар до нуля не доводит (жертва богата); в наборе "
          f"с актом {len(members)}, без акта {len(members_no)}")

    e2 = E.GameStateExtractor()
    e2.extract(syn(10), {}, 1)
    st2 = e2.extract(syn(2, foe=3), {}, 2)
    ev2 = getattr(e2, "last_attack_event", {}) or {}
    acts2 = ev2.get("strikes") or []
    st2m = getattr(st2, "state", st2)
    dof2 = {str(eid): float(getattr(e, "current_dof", 0.0))
            for eid, e in (getattr(st2m, "entities", None) or {}).items()}
    vecs = {eid: ["goto_1"] for eid in dof2}
    gr2 = G.world_graph(vecs, {}, dof2, strikes=acts2)
    m2 = core.calc_members(st2m, G.observation_context(gr2, dof2))
    gr2_no = G.world_graph(vecs, {}, dof2, strikes=())
    m2_no = core.calc_members(st2m, G.observation_context(gr2_no, dof2))
    d2 = float(dof2.get("unit_5", 0.0))
    dd2 = float((acts2[0].get("delta") if acts2 else 0.0) or 0.0)
    print(f"  [бедная жертва] DoF unit_5 {d2:.4f} + величина {dd2:+.4f} = {d2 + dd2:+.4f}; "
          f"в наборе с актом {len(m2)}, без акта {len(m2_no)}; узлы {sorted(dof2)}")
    check("П3 при ударе, доводящем цель до нуля, свидетель подтверждает метку: узел силы "
          "уходит из набора счёта, а без акта остаётся",
          ("diplomacy_3" not in m2) and ("diplomacy_3" in m2_no) and (d2 + dd2) <= 1e-15,
          f"с актом {'diplomacy_3' in m2}, без акта {'diplomacy_3' in m2_no}")

    # ── П4: наши узлы не помечаются
    check("П4 ни одна метка не легла на нашу сущность",
          all(not str(h.get("узел") or "").startswith(("unit_", "city_", "tech_"))
              for h in hosts),
          f"узлы меток {[h.get('узел') for h in hosts]}")

    # ── П5: инертность на захвате без наблюдённого удара
    e_live = E.GameStateExtractor()
    n_strikes = n_hosts = n_edges = 0
    prev_ob, last = None, {}
    for i, rec in enumerate(rows):
        ob = rec["observation"]
        last = SO.measure_step(ob, rec.get("info") or {}, rec.get("turn", i + 1), e_live,
                               prev_obs=prev_ob, my_player_id=0)
        ev_live = getattr(e_live, "last_attack_event", {}) or {}
        n_strikes += len(ev_live.get("strikes") or [])
        n_hosts += len(ev_live.get("label_hosts") or [])
        gr_live = G.world_graph(last["vectors"], last["fields"], last["dof"],
                                catalogue=last["catalogue"], known_techs=last["known_techs"],
                                raw_menus=last["raw_menus"],
                                strikes=ev_live.get("strikes") or ())
        n_edges += sum(1 for a in gr_live.acts if a.id.startswith("strike:"))
        prev_ob = ob
    print(f"  захват: шагов {len(rows)}, ударов {n_strikes}, меток {n_hosts}, рёбер {n_edges}; "
          f"в наборе {last.get('в_расчёте')}, индекс ядра {last.get('индекс_ядра')}")
    check("П5 на захвате без наблюдённого удара ни актов, ни меток, ни рёбер не появилось",
          n_strikes == 0 and n_hosts == 0 and n_edges == 0,
          f"удары {n_strikes}, метки {n_hosts}, рёбра {n_edges}")

    print(f"\nитог: ok {OK}, плохо {BAD}")
    sys.exit(1 if BAD else 0)


main()
