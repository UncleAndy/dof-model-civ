#!/usr/bin/env python
"""Замер влияния работ на террейне на выход клетки (не догадка — измерение).

Правила civ2civ3 («ирригация +1 еда», «шахта +1 щит») НЕ берём на веру: играем
матч, ставим рабочему работу (`irrigation` / `build_road` / `mine` / ...) и следим
за `map['output'][x][y]` ТОЙ ЖЕ клетки по ходам, пока выход не изменится.
Полученная таблица «террейн + экстры -> Δеда/Δщиты/Δторговля» — то, чем можно
кормить бридж.

Сначала печатает все действия рабочих с их параметрами: если в параметрах есть
координаты, цель известна точно; если нет — работа идёт на клетке юнита.

    python scripts/measure_terrain_effect.py --turns 12
"""
import argparse
import json
import os
import signal
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)

from civrealm.freeciv.map.map_const import EXTRA_NAMES, TERRAIN_NAMES  # noqa: E402

WORK_PREFIXES = ("irrigation", "irrigate", "mine", "build_road", "road", "railroad",
                 "cultivate", "transform", "plant", "fortress", "airbase")

#: Что измерять в первую очередь. `cultivate`/`plant`/`transform` меняют сам
#: террейн (это уже замерено: Forest ⇄ Swamp за 4 хода), поэтому их цена — не
#: эффект экстры; нужны работы, которые ставят Irrigation/Mine/Road.
WORK_PREFERENCE = [
    ("build_road", "irrigation", "irrigate"),   # ставит экстру на любой земле
    ("mine",),
    ("railroad", "farmland"),
    ("cultivate", "plant", "transform", "fortress", "airbase"),
]


def pick_work(actions: dict, only: str | None = None) -> tuple[str, object] | None:
    """Лучшая валидная работа на клетке: сначала те, что ставят экстру.

    `only` сужает выбор до одной работы (`irrigation`, `mine`, `road`, …) — иначе замер
    всегда брал бы дорогу, и вопрос «даёт ли ирригация пищу» остался бы незакрытым.
    """
    if only:
        for name, params in actions.items():
            if params and name.startswith(only):
                return name, params
        return None
    for group in WORK_PREFERENCE:
        for name, params in actions.items():
            if params and any(name.startswith(p) for p in group):
                return name, params
    return None


class MatchTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise MatchTimeout("match exceeded budget")


def tile_of(obs, x, y):
    oa = np.asarray(obs["map"]["output"])
    ta = np.asarray(obs["map"]["terrain"])
    ea = np.asarray(obs["map"]["extras"])
    x %= oa.shape[0]
    y %= oa.shape[1]
    out = tuple(int(v) for v in np.asarray(oa[x][y]).ravel()[:3])
    t = int(ta[x][y])
    tname = TERRAIN_NAMES[t] if t < len(TERRAIN_NAMES) else f"?{t}"
    extras = sorted(EXTRA_NAMES[i] for i in range(ea.shape[2]) if ea[x][y][i]) \
        if ea.ndim == 3 else []
    return tname, extras, out


def units_by_key(obs) -> dict:
    """`obs['unit']` с ключами и как есть, и как строка: ключи бывают int и str."""
    out = {}
    for k, v in (obs.get("unit") or {}).items():
        if not isinstance(v, dict):
            continue
        out[k] = v
        out[str(k)] = v
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--turns", type=int, default=12)
    #: Замер одной работы: `--only irrigation` / `--only mine` / `--only road`.
    #: Без него берётся первая доступная (в порядке предпочтения — дороги).
    p.add_argument("--only", default=None)
    args = p.parse_args()

    import warnings
    warnings.filterwarnings("ignore")
    os.environ["PYTHONWARNINGS"] = "ignore"

    signal.signal(signal.SIGALRM, _on_alarm)
    #: Бюджет матча: по умолчанию 560 с, но замер одной работы требует времени —
    #: работа идёт 3-4 хода, и матч надо довести до её конца.
    signal.alarm(int(os.environ.get("TERRAIN_MEASURE_BUDGET", "560")))
    try:
        from civrealm.freeciv.utils.port_utils import Ports
        import gymnasium
        from civrealm.configs import fc_args

        # Мёртвый слот (его игра не перезапустилась) валится на reset, поэтому
        # берём слоты, пока какой-нибудь не поднимется.
        import time

        obs = info = None
        env = gymnasium.make("civrealm/FreecivBase-v0")
        for attempt in range(5):
            port = Ports.get()
            print(f"slot: {port} (попытка {attempt + 1})", flush=True)
            fc_args["client_port"] = port
            try:
                # Зависший слот (его игра не перезапустилась) не отвечает и не
                # падает, поэтому reset ограничен по времени: иначе перебор
                # слотов бесполезен — первый же мёртвый съест весь бюджет.
                signal.alarm(90)
                obs, info = env.reset(client_port=port)
                # Бюджет на попытку, а не на весь прогон: зависший матч не должен
                # съедать остальные попытки.
                signal.alarm(200)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  слот {port} не поднялся: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(3)
        if obs is None:
            print("ERR: ни один слот не поднялся")
            raise SystemExit(5)

        # 1. Что вообще предлагают рабочие и есть ли в параметрах цель.
        print("\n=== ДЕЙСТВИЯ ЮНИТОВ, СВЯЗАННЫЕ С РАБОТАМИ ===")
        for actor_id, actions in ((info.get("available_actions") or {}).get("unit") or {}).items():
            for name, params in actions.items():
                if any(name.startswith(w) for w in WORK_PREFIXES):
                    print(f"  unit {actor_id}: {name} | params={json.dumps(params, default=str)[:160]}")

        # 2. Ставим первую доступную работу и следим за клеткой.
        watch = {}          # unit_id -> (x, y, action, before, terrain, extras)
        results = defaultdict(list)
        last_turn = None
        stuck = 0
        for step in range(args.turns):
            turn = info.get("turn", step + 1)
            # Сторож: если матч перестал двигать ходы, попытка закрывается, и
            # серия переходит к следующему слоту (вместо тихого зависания).
            if turn == last_turn:
                stuck += 1
                if stuck >= 5:
                    print(f"  ход не двигается ({turn}) 5 итераций — закрываю попытку")
                    break
            else:
                stuck = 0
            last_turn = turn
            avail = (info.get("available_actions") or {}).get("unit") or {}
            units = units_by_key(obs)
            placed = []
            busy_tiles = {(w[0], w[1]) for w in watch.values()}
            for actor_id, actions in avail.items():
                if actor_id in watch:
                    continue
                u = units.get(actor_id)
                if not isinstance(u, dict) or u.get("x") is None:
                    continue
                choice = pick_work(actions, args.only)
                if choice is None:
                    continue
                name, params = choice
                x, y = int(u["x"]), int(u["y"])
                # Рабочие в начале стоят стопкой: если все поставят работу на одну
                # клетку, они мешают друг другу и работа может не продвигаться.
                # Поэтому одна клетка — один рабочий.
                if (x, y) in busy_tiles:
                    continue
                tname, extras, before = tile_of(obs, x, y)
                watch[actor_id] = (x, y, name, before, tname, extras)
                busy_tiles.add((x, y))
                placed.append(f"unit {actor_id} @({x},{y}) {tname}"
                              f"{'+' + ','.join(extras) if extras else ''} -> {name} "
                              f"было {before}")
                env.step(("unit", actor_id, name))
            for line in placed:
                print(f"turn {turn}: поставлено: {line}", flush=True)

            # 3. Проверяем, изменился ли выход под наблюдением.
            for actor_id, (x, y, name, before, tname, extras) in list(watch.items()):
                now_t, now_e, now = tile_of(obs, x, y)
                # Работа может изменить и сам террейн, и набор экстр, и выход.
                # Ловим всё три: иначе «irrigation прошла, но еды не прибавила»
                # выглядит как «работа не завершилась».
                if now != before or list(now_e) != list(extras) or now_t != tname:
                    key = (now_t, tuple(now_e), name)
                    delta = tuple(int(n) - int(b) for n, b in zip(now, before))
                    results[key].append(delta)
                    print(f"turn {turn}: ИЗМЕНЕНИЕ {tname} @({x},{y}) {name}: "
                          f"{before} -> {now} (Δ={delta}); "
                          f"террейн {tname} -> {now_t}; "
                          f"экстры {list(extras)} -> {list(now_e)}")
                    watch.pop(actor_id)

            obs, _r, term, trunc, info = env.step(None)
            if term or trunc:
                print("(игра окончена)")
                break

        print("\n=== ИТОГ ЗАМЕРА: террейн + работа -> Δ(еда, щиты, торговля) ===")
        if not results:
            print("  изменений не поймано (работа не завершилась в пределах прогона)")
        for (tname, extras, name), deltas in sorted(results.items()):
            ex = f"+{','.join(extras)}" if extras else ""
            print(f"  {tname}{ex} {name}: {deltas}")

        print("\n=== НЕ ДОЖДАЛИСЬ ЗАВЕРШЕНИЯ ===")
        for actor_id, (x, y, name, before, tname, extras) in watch.items():
            u = units_by_key(obs).get(actor_id) or {}
            # `activity` показывает, идёт ли работа вообще: без этого «нет
            # изменения» неотличимо от «работа не выполняется».
            print(f"  unit {actor_id} {tname} @({x},{y}) {name}: осталось {before}; "
                  f"activity={u.get('activity')!r} moves_left={u.get('moves_left')!r}")
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    import traceback

    try:
        main()
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        print(f"ERR: {type(exc).__name__}: {exc}")
        raise SystemExit(3)
