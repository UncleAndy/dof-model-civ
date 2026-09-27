#!/usr/bin/env python
"""Замер работ: превращения террейна, цепочка работ и достижимость после дороги.

Три вопроса, на которые нужны факты из мира (а не из правилсета):

1. **Превращение**: `cultivate`/`plant`/`transform_terrain` меняют сам террейн.
   Замерено, что Forest+Pheasant ⇄ Swamp за 4 хода, но неизвестно, какой ВЫХОД у
   результата — а значит эти работы невидимы: выход клетки не менялся, потому что
   сравнивался не с тем состоянием. Пишем таблицу «до → после» с выходом.
2. **Цепочка**: после первой работы на клетке могут стать валидными следующие
   (`irrigation` → `farmland` и т.п.). Валидность сообщает сам сервер в
   `available_actions`, поэтому её надо просто записывать по ходам, а не угадывать.
3. **Дорога**: в этом стенде дорога не меняет выход клетки (замерено). Тогда её
   ценность может быть только в **достижимости**: дорога под юнитом меняет набор
   доступных `goto_*`. Сравниваем набор до и после завершения дороги.

Ничего не додумывает: каждая строка — наблюдение. Пишет JSONL в
`work_chain_measurements.jsonl` (путь можно переопределить).

    python scripts/measure_work_chain.py --turns 40
"""
import argparse
import json
import os
import signal
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)

from civrealm.freeciv.map.map_const import EXTRA_NAMES, TERRAIN_NAMES  # noqa: E402

#: Работы в порядке предпочтения: сначала те, что ставят экстру (их эффект уже
#: измерен нулём, но цепочка после них — нет), потом превращения террейна.
WORK_ORDER = ("irrigation", "irrigate", "mine", "build_road", "road",
              "cultivate", "plant", "transform_terrain", "railroad", "farmland")
WORK_PREFIXES = tuple(WORK_ORDER)
#: Работы, меняющие сам террейн (их результат и есть измеряемая величина).
TRANSFORM_ACTIONS = ("cultivate", "plant", "transform_terrain")


class MatchTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise MatchTimeout("match exceeded budget")


def tile_of(obs, x, y):
    """Террейн, экстры и выход клетки — как их отдаёт карта."""
    out_layer = np.asarray(obs["map"]["output"])
    terr_layer = np.asarray(obs["map"]["terrain"])
    extras_layer = np.asarray(obs["map"]["extras"])
    x %= out_layer.shape[0]
    y %= out_layer.shape[1]
    out = tuple(int(v) for v in np.asarray(out_layer[x][y]).ravel()[:3])
    tid = int(terr_layer[x][y])
    tname = TERRAIN_NAMES[tid] if 0 <= tid < len(TERRAIN_NAMES) else f"?{tid}"
    extras = sorted(EXTRA_NAMES[i] for i in range(extras_layer.shape[2])
                    if extras_layer[x][y][i]) if extras_layer.ndim == 3 else []
    return tname, extras, out


def valid_work(actions: dict) -> dict:
    """Какие работы валидны у актёра (валидность = непустые параметры)."""
    return {name: params for name, params in (actions or {}).items()
            if params and any(name.startswith(p) for p in WORK_PREFIXES)}


def goto_reach(actions: dict) -> tuple[int, int]:
    """Сколько `goto_*` предложено и до какой наибольшей дистанции (достижимость)."""
    dists = []
    for name in (actions or {}):
        if name.startswith("goto_"):
            tail = name[len("goto_"):]
            try:
                dists.append(int(tail))
            except ValueError:
                continue
    return len(dists), (max(dists) if dists else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=40)
    ap.add_argument("--prefer", default="transform",
                    choices=["transform", "road", "irrigation", "mine", "any"],
                    help="какие работы ставить в первую очередь (за один прогон "
                         "успевает завершиться не всё, поэтому замеры разделены)")
    ap.add_argument("--wander", action="store_true",
                    help="если предпочтённой работы нет — юнит идёт куда-нибудь "
                         "сам (`goto_N` без координат), чтобы попасть на террейн, "
                         "где эта работа валидна")
    ap.add_argument("--out", default=os.path.join(HERE, "work_chain_measurements.jsonl"))
    args = ap.parse_args()

    import warnings
    warnings.filterwarnings("ignore")
    os.environ["PYTHONWARNINGS"] = "ignore"

    signal.signal(signal.SIGALRM, _on_alarm)

    import gymnasium
    from civrealm.configs import fc_args
    from civrealm.freeciv.utils.port_utils import Ports

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs = info = None
    for attempt in range(6):
        port = Ports.get()
        print(f"слот: {port} (попытка {attempt + 1})", flush=True)
        fc_args["client_port"] = port
        try:
            signal.alarm(90)
            obs, info = env.reset(client_port=port)
            signal.alarm(900)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  слот {port} не поднялся: {type(exc).__name__}", flush=True)
            time.sleep(3)
    if obs is None:
        print("ERR: ни один слот не поднялся")
        raise SystemExit(5)

    try:
        my_id = env.get_playerid()
    except Exception:  # noqa: BLE001
        my_id = None
    print(f"мой player_id: {my_id}", flush=True)

    #: unit_id -> {"x","y","action","started_turn","before", "reach_before",
    #:             "phase": "work"|"chain"|"transform"}
    watching: dict = {}
    rows = 0
    fh = open(args.out, "a", encoding="utf-8")

    def emit(row: dict) -> None:
        nonlocal rows
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        rows += 1

    last_turn = None
    stuck = 0
    for step in range(args.turns):
        turn = info.get("turn", step + 1)
        if turn == last_turn:
            stuck += 1
            if stuck >= 6:
                print(f"  ход не двигается ({turn}) — закрываю прогон", flush=True)
                break
        else:
            stuck = 0
        last_turn = turn

        unit_actions = (info.get("available_actions") or {}).get("unit") or {}
        units = obs.get("unit") or {}
        if not isinstance(units, dict):
            units = {}

        # 1. Наблюдение за уже поставленными работами: сменились ли экстры/террейн.
        for unit_id, w in list(watching.items()):
            try:
                tname, extras, out = tile_of(obs, w["x"], w["y"])
            except Exception:  # noqa: BLE001
                continue
            changed = (tname != w["before"][0]) or (extras != w["before"][1])
            row = {
                "kind": "watch", "turn": turn, "unit": unit_id, "x": w["x"], "y": w["y"],
                "action": w["action"], "phase": w["phase"],
                "terrain_before": w["before"][0], "extras_before": w["before"][1],
                "output_before": list(w["before"][2]),
                "terrain": tname, "extras": extras, "output": list(out),
                "changed": changed,
            }
            # 2. Цепочка: что стало валидным на этой клетке после работы.
            for aid, acts in unit_actions.items():
                if str(aid) == str(unit_id):
                    row["valid_work_now"] = sorted(valid_work(acts))
                    row["goto_now"] = goto_reach(acts)
            emit(row)
            # Пост-наблюдение за дорогой идёт ПЕРЕД проверкой «изменилось»: в эти
            # ходы клетка уже не меняется, а достижимость всё ещё измеряется.
            if w["phase"] == "post-road" and w.get("post_left", 0) > 0:
                w["post_left"] -= 1
                n_now, far_now = goto_reach(
                    next((a for aid, a in unit_actions.items()
                          if str(aid) == str(unit_id)), {}))
                emit({"kind": "reach", "turn": turn, "unit": unit_id,
                      "x": w["x"], "y": w["y"], "lag": 2 - w["post_left"],
                      "goto_before": w.get("reach_before", [None, None]),
                      "goto_after": [n_now, far_now], "extras_now": extras})
                if w["post_left"] <= 0:
                    del watching[unit_id]
                continue
            if changed:
                if w["phase"] == "road":
                    # Достижимость после дороги: сразу на ходу завершения И ещё
                    # два хода — сервер может пересчитать маршруты не мгновенно,
                    # поэтому один замер «в лоб» был бы неполным.
                    n_now, far_now = goto_reach(
                        next((a for aid, a in unit_actions.items()
                              if str(aid) == str(unit_id)), {}))
                    emit({"kind": "reach", "turn": turn, "unit": unit_id,
                          "x": w["x"], "y": w["y"], "lag": 0,
                          "goto_before": w.get("reach_before", [None, None]),
                          "goto_after": [n_now, far_now],
                          "extras_now": extras})
                    w["phase"] = "post-road"
                    w["post_left"] = 2
                    w["before"] = (tname, extras, out)
                    continue
                if w["phase"] == "post-road" and w.get("post_left", 0) > 0:
                    w["post_left"] -= 1
                    n_now, far_now = goto_reach(
                        next((a for aid, a in unit_actions.items()
                              if str(aid) == str(unit_id)), {}))
                    emit({"kind": "reach", "turn": turn, "unit": unit_id,
                          "x": w["x"], "y": w["y"], "lag": 2 - w["post_left"],
                          "goto_before": w.get("reach_before", [None, None]),
                          "goto_after": [n_now, far_now], "extras_now": extras})
                    if w["post_left"] <= 0:
                        del watching[unit_id]
                    continue
                # Работа завершена: снимаем наблюдение и позволяем юниту дальше.
                del watching[unit_id]

        # 3. Новые работы: берём юнитов, которым есть что делать.
        for actor_id, acts in list(unit_actions.items()):
            if actor_id in watching:
                continue
            w_avail = valid_work(acts)
            if not w_avail:
                continue
            u = units.get(actor_id) or units.get(str(actor_id)) or {}
            if not isinstance(u, dict):
                continue
            owner = u.get("owner", my_id)
            if my_id is not None and str(owner) != str(my_id):
                continue
            x, y = u.get("x"), u.get("y")
            if x is None or y is None:
                continue
            x, y = int(x), int(y)
            # Выбор работы по приоритету прогона: за один матч успевает
            # завершиться не всё (превращение — 4 хода, дорога — 3), поэтому
            # замеры работ разведены по прогонам, а не смешаны.
            preference = {
                "transform": (*TRANSFORM_ACTIONS, "build_road", "irrigation", "mine"),
                "road": ("build_road", "road", "railroad"),
                "irrigation": ("irrigation", "irrigate"),
                "mine": ("mine",),
                "any": (*TRANSFORM_ACTIONS, *WORK_ORDER),
            }[args.prefer]
            chosen = next((name for name in preference if name in w_avail), None)
            if chosen is None:
                # Ирригация и шахта валидны только на подходящем террейне, а
                # координат в `goto_N` нет — значит рабочего нельзя «привести»
                # к цели. Поэтому в режиме `--wander` он сам уходит (какой-то
                # `goto_N`), а мы записываем, что стало валидным на новой клетке.
                if args.wander:
                    # Валидность = непустые параметры: без этой проверки выбирался
                    # `goto_N`, которого сервер не предлагал, и он отклонял
                    # действие («Action goto_6 of 117 is not valid»).
                    gotos = [name for name, params in (acts or {}).items()
                             if name.startswith("goto_") and params]
                    if gotos:
                        try:
                            tname, extras, tout = tile_of(obs, x, y)
                        except Exception:  # noqa: BLE001
                            tname, extras, tout = None, None, None
                        emit({"kind": "sample", "turn": turn, "unit": actor_id,
                              "x": x, "y": y, "terrain": tname, "extras": extras,
                              "output": list(tout) if tout else None,
                              "valid_work": sorted(w_avail),
                              "goto": list(goto_reach(acts))})
                        pick = gotos[min(turn, len(gotos) - 1)]
                        try:
                            obs, reward, term, trunc, info = env.step(
                                ("unit", actor_id, pick))
                            emit({"kind": "roam", "turn": turn, "unit": actor_id,
                                  "x": x, "y": y, "action": pick})
                        except Exception as exc:  # noqa: BLE001
                            emit({"kind": "err", "turn": turn, "unit": actor_id,
                                  "action": pick,
                                  "error": f"{type(exc).__name__}: {exc}"})
                        break
                continue
            phase = "transform" if chosen in TRANSFORM_ACTIONS else (
                "road" if chosen.startswith(("build_road", "road", "railroad")) else "work")
            try:
                before = tile_of(obs, x, y)
            except Exception:  # noqa: BLE001
                continue
            n_before, far_before = goto_reach(acts)
            # Параметры движения: без них нельзя увести рабочего на землю, где
            # валидны ирригация/шахта (на Forest/Swamp их не предлагают).
            goto_params = {name: params for name, params in (acts or {}).items()
                           if name.startswith("goto_") and params}
            emit({"kind": "start", "turn": turn, "unit": actor_id, "x": x, "y": y,
                  "action": chosen, "phase": phase,
                  "terrain": before[0], "extras": before[1],
                  "output": list(before[2]),
                  "valid_work": sorted(w_avail), "goto": [n_before, far_before],
                  "goto_params_sample": dict(list(goto_params.items())[:2]),
                  "type": str(u.get("rule_name") or u.get("type") or "?")})
            watching[actor_id] = {"x": x, "y": y, "action": chosen, "phase": phase,
                                  "before": before, "reach_before": [n_before, far_before]}
            try:
                obs, reward, term, trunc, info = env.step(("unit", actor_id, chosen))
            except Exception as exc:  # noqa: BLE001
                emit({"kind": "err", "turn": turn, "unit": actor_id, "action": chosen,
                      "error": f"{type(exc).__name__}: {exc}"})
                del watching[actor_id]
            break  # одна постановка за шаг: так работа точно доходит до конца

        # 4. Конец хода: только `None` двигает ход.
        obs, reward, term, trunc, info = env.step(None)
        if term or trunc:
            print(f"  матч завершён на ходу {turn}", flush=True)
            break

    fh.close()
    print(f"\nстрок записано: {rows} → {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
