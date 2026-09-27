#!/usr/bin/env python
"""Дорога: даёт ли она ход (движение), а не только выход клетки?

Уже измерено: `build_road` СТАВИТ экстру Road, но выход клетки не меняет — значит
ценность дороги, если она есть, не в еде/щитах/торговле, а в ДВИЖЕНИИ. Первый замер
движения был слабым: юнит стоял *на* дороге, а дорога проявляется у идущего *вдоль*.
Слабость названа, теперь закрывается.

Что измеряется точно: цена ОДНОГО шага в очках движения. У команды `goto_N` цель
вычислима (N — это dir8, измерено по исходнику стенда), поэтому «шаг на дорогу» и
«шаг на ту же местность без дороги» различаются по построению, а не по догадке.

ГИПОТЕЗЫ ОБЪЯВЛЕНЫ ДО ДАННЫХ:

  H1 (цена шага). Шаг НА клетку с дорогой стоит 1/3 очка движения, шаг на такую же
     клетку без дороги — 1.0. Проверка: остаток движения после шага.
  H0 (альтернатива, тоже законный исход). Дорога движения не меняет: цена шага на
     дорогу равна цене шага без неё. Тогда «дорога не даёт ничего и в движении», и
     это честный измеренный ноль, а не «не проверено».

Порог вердикта (задан ДО данных): H1 принимается, если цена шага на дорогу строго
меньше цены шага на ту же местность без дороги НЕ МЕНЕЕ чем в 6 из 8 пар
«местность→местность» и медиана отношения ≤ 0.5; иначе H0. Пары строятся по
(террейн_откуда, террейн_куда) и сравниваются только внутри пары.

    python scripts/measure_road_value.py --turns 30
"""
import argparse
import json
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)

#: Правило направлений — ОДНО на проект (первая половина правки п.6).
from brain.forecast.live import direction_target  # noqa: E402

MOVES_KEYS = ("moves", "moves_left", "move_left", "moves_remaining")


def pick_moves(unit: dict):
    for key in MOVES_KEYS:
        if key in unit and unit[key] is not None:
            return key, unit[key]
    return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=30)
    parser.add_argument("--out", default="road_value.jsonl")
    parser.add_argument("--unit-keys", action="store_true",
                        help="напечатать ключи записи юнита на первом ходу")
    args = parser.parse_args()

    import warnings
    warnings.filterwarnings("ignore")
    os.environ["PYTHONWARNINGS"] = "ignore"

    def _on_alarm(signum, frame):
        raise TimeoutError("budget")

    signal.signal(signal.SIGALRM, _on_alarm)

    import gymnasium
    from civrealm.configs import fc_args
    from civrealm.freeciv.utils.port_utils import Ports
    from civrealm.freeciv.map.map_const import EXTRA_NAMES, TERRAIN_NAMES

    road_index = None
    for index, name in enumerate(EXTRA_NAMES):
        if str(name).lower() == "road":
            road_index = index
    if road_index is None:
        print("ВНИМАНИЕ: в EXTRA_NAMES нет Road — дорогу не отличить от прочего")

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs = info = None
    for _attempt in range(5):
        port = Ports.get()
        print(f"слот {port}", flush=True)
        fc_args["client_port"] = port
        try:
            signal.alarm(90)
            obs, info = env.reset(client_port=port)
            signal.alarm(0)
            break
        except Exception as exc:  # noqa: BLE001
            signal.alarm(0)
            print(f"  не поднялся: {type(exc).__name__}", flush=True)
            time.sleep(3)
    if obs is None:
        raise SystemExit(5)

    rows = []

    def emit(row):
        rows.append(row)
        with open(args.out, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def layer_tile(layer, x, y):
        try:
            return layer[int(x)][int(y)]
        except Exception:  # noqa: BLE001
            return None

    def road_at(map_obs, x, y):
        if road_index is None:
            return None
        cell = layer_tile(map_obs.get("extras"), x, y)
        if cell is None:
            return None
        try:
            return bool(float(cell[road_index]))
        except Exception:  # noqa: BLE001
            try:
                return bool(cell[road_index])
            except Exception:  # noqa: BLE001
                return None

    def terrain_at(map_obs, x, y):
        cell = layer_tile(map_obs.get("terrain"), x, y)
        try:
            index = int(cell)
        except Exception:  # noqa: BLE001
            return "?"
        if index == 255 or not 0 <= index < len(TERRAIN_NAMES):
            return "?"
        return TERRAIN_NAMES[index]

    def shape_of(map_obs):
        shape = getattr(map_obs.get("output"), "shape", None)
        return (int(shape[0]), int(shape[1])) if shape is not None else None

    def neighbour(map_obs, pos, dir8):
        """Клетка в направлении dir8 — ТОЙ ЖЕ арифметикой, что и прогноз.

        Правило одно на проект (`direction_target`): X — цилиндр, Y — полюс,
        за краем клетки нет. Дублировать его здесь значило бы завести второе
        правило, которое разойдётся с первым.
        """
        return direction_target(pos, dir8, shape_of(map_obs))

    def my_player_no(obs):
        """Номер моей державы — по записи игрока, а не по ключу словаря.

        Ловушка живых ключей: `obs['player']` живьём ключуется целыми, в фикстурах
        строками; смотрим ЗНАЧЕНИЯ, поэтому тип ключа не важен.
        """
        for rec in (obs.get("player") or {}).values():
            if isinstance(rec, dict) and rec.get("is_me"):
                return rec.get("playerno")
        for rec in (obs.get("player") or {}).values():
            if isinstance(rec, dict):
                return rec.get("playerno")
        return None

    printed_keys = False
    road_tiles = 0
    roads: set = set()
    roads_goal = 2
    build_in_flight = None
    print(f"индекс Road в EXTRA_NAMES: {road_index} "
          f"({EXTRA_NAMES[road_index] if road_index is not None else '—'}), "
          f"всего экстр: {len(EXTRA_NAMES)}", flush=True)
    for turn in range(args.turns):
        map_obs = obs.get("map") or {}
        units = obs.get("unit") or {}
        mine = my_player_no(obs)
        if turn == 0:
            extras = map_obs.get("extras")
            print(f"слой extras: shape={getattr(extras, 'shape', None)}", flush=True)
        if args.unit_keys and not printed_keys and units:
            printed_keys = True
            first = next((u for u in units.values() if isinstance(u, dict)), {})
            print(f"=== ключи записи юнита: {sorted(first.keys())}", flush=True)

        offered_units = (info.get("available_actions") or {}).get("unit") or {}
        offered_units_all = offered_units

        # Обновляем список дорог: `road_at` читает слой экстр (Road = индекс 11).
        shape_now = shape_of(map_obs)
        if shape_now and road_index is not None:
            for x in range(shape_now[0]):
                for y in range(shape_now[1]):
                    if road_at(map_obs, x, y):
                        roads.add((x, y))
        if build_in_flight is not None and build_in_flight[1] in roads:
            print(f"ход {turn}: дорога появилась на {build_in_flight[1]}", flush=True)
            emit({"turn": turn, "kind": "road_built",
                  "tile": list(build_in_flight[1])})
            build_in_flight = None
        # Дорог на карте может не быть вовсе (измерено: 0 на старте). Тогда «шаг на
        # дорогу» измерить нечем, и это НЕ «дорога бесполезна» — это «дороги нет».
        # Поэтому дорога СТРОИТСЯ, и не одна: шаг «дорога→дорога» — тот самый
        # случай, на котором сорвался прежний слабый замер.
        if build_in_flight is None and len(roads) < roads_goal:
            best = None
            fallback = None
            for uid, unit in units.items():
                if not isinstance(unit, dict):
                    continue
                if mine is not None and unit.get("owner") is not None \
                        and str(unit.get("owner")) != str(mine):
                    continue
                acts = offered_units_all.get(uid) or offered_units_all.get(str(uid)) or {}
                if not isinstance(acts, dict) or not acts.get("build_road"):
                    continue
                pos = (unit.get("x"), unit.get("y"))
                if not all(isinstance(v, (int, float)) for v in pos):
                    continue
                if fallback is None:
                    fallback = (uid, unit, pos)
                # Рядом с уже существующей дорогой — предпочтительно.
                for d in range(8):
                    nxt = direction_target(pos, d, shape_now)
                    if nxt in roads:
                        best = (uid, unit, pos)
                        break
                if best is not None:
                    break
            chosen = best or fallback
            if chosen is not None:
                uid, unit, pos = chosen
                try:
                    signal.setitimer(signal.ITIMER_REAL, 20)
                    obs, _r, term, trunc, info = env.step(("unit", uid, "build_road"))
                    signal.setitimer(signal.ITIMER_REAL, 0)
                except Exception as exc:  # noqa: BLE001
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    emit({"turn": turn, "kind": "road_build_err", "unit": str(uid),
                          "error": f"{type(exc).__name__}: {exc}"})
                    print(f"ход {turn}: постройка дороги НЕ вернулась: "
                          f"{type(exc).__name__}: {exc}", flush=True)
                    roads_goal = 0        # больше не пробуем, чтобы не терять матч
                else:
                    build_in_flight = (str(uid), pos)
                    next_to_road = any(direction_target(pos, d, shape_now) in roads
                                       for d in range(8))
                    emit({"turn": turn, "kind": "road_build", "unit": str(uid),
                          "tile": list(pos), "next_to_road": next_to_road,
                          "terrain": terrain_at(map_obs, *pos),
                          "type": unit.get("type_rule_name")})
                    print(f"ход {turn}: {unit.get('type_rule_name')} ставит дорогу "
                          f"на {pos} ({terrain_at(map_obs, *pos)}); "
                          f"рядом с дорогой: {next_to_road}", flush=True)

        if turn == 0:
            # Сколько дорог вообще есть на раскрытой карте — иначе «нет эффекта»
            # нельзя отличить от «не было ни одной дороги».
            shape = shape_of(map_obs)
            seen = set()
            if shape and road_index is not None:
                for x in range(shape[0]):
                    for y in range(shape[1]):
                        if road_at(map_obs, x, y):
                            seen.add((x, y))
            road_tiles = len(seen)
            print(f"дорог на раскрытой карте: {road_tiles}", flush=True)

        for uid, unit in units.items():
            if not isinstance(unit, dict):
                continue
            # Строителя дороги не уводить: новый приказ отменяет работу, и дорога
            # не появится никогда (на этом и сорвался первый заход замера).
            if build_in_flight is not None and str(uid) == build_in_flight[0]:
                continue
            # Только свои юниты: чужой юнит чужими командами не пошевелить.
            if mine is not None and unit.get("owner") is not None:
                if str(unit.get("owner")) != str(mine):
                    continue
            key, moves = pick_moves(unit)
            move_rate = unit.get("type_move_rate")
            pos = (unit.get("x"), unit.get("y"))
            if pos[0] is None or pos[1] is None or moves is None:
                continue
            try:
                full = float(moves) >= float(move_rate or 0)
            except Exception:  # noqa: BLE001
                full = False
            if not full:
                continue
            acts = offered_units.get(uid) or offered_units.get(str(uid)) or {}
            gotos = {name: params for name, params in (acts or {}).items()
                     if name.startswith("goto_") and params}
            if not gotos:
                continue
            # Выбираем шаг СНАЧАЛА на дорогу (если предлагается), иначе любой:
            # так за один прогон собираются оба класса.
            chosen = None
            for name in sorted(gotos):
                dir8 = int(name.rsplit("_", 1)[-1])
                target = neighbour(map_obs, pos, dir8)
                if target is None:
                    continue
                to_road = road_at(map_obs, *target)
                if to_road:
                    chosen = (name, dir8, target, True)
                    break
                if chosen is None:
                    chosen = (name, dir8, target, False)
            if chosen is None:
                continue
            name, dir8, target, to_road = chosen
            terrain_from = terrain_at(map_obs, *pos)
            terrain_to = terrain_at(map_obs, *target)
            row = {
                "turn": turn, "unit": str(uid),
                "type": unit.get("type_rule_name") or unit.get("type"),
                "move_rate": move_rate, "moves_key": key,
                "moves_before": moves,
                "from": list(pos), "to": list(target), "dir8": dir8,
                "action": name,
                "road_from": road_at(map_obs, *pos),
                "road_to": road_at(map_obs, *target),
                "terrain_from": terrain_from, "terrain_to": terrain_to,
                "offered_gotos": len(gotos),
            }
            try:
                signal.setitimer(signal.ITIMER_REAL, 20)
                obs, _reward, term, trunc, info = env.step(("unit", uid, name))
                signal.setitimer(signal.ITIMER_REAL, 0)
            except Exception as exc:  # noqa: BLE001
                signal.setitimer(signal.ITIMER_REAL, 0)
                row["error"] = f"{type(exc).__name__}: {exc}"
                emit(row)
                print(f"  ход {turn} шаг {name} НЕ вернулся: {row['error']}",
                      flush=True)
                break
            after = obs.get("unit") or {}
            new_rec = after.get(uid) or after.get(str(uid)) or {}
            _k2, moves_after = pick_moves(new_rec if isinstance(new_rec, dict) else {})
            row["moves_after"] = moves_after
            try:
                row["cost"] = (round(float(moves) - float(moves_after), 3)
                               if moves_after is not None else None)
            except Exception:  # noqa: BLE001
                row["cost"] = None
            row["landed"] = [new_rec.get("x"), new_rec.get("y")] \
                if isinstance(new_rec, dict) else None
            emit(row)
            print(f"  ход {turn} {row['type']} {pos}→{target} dir8={dir8} "
                  f"дорога={to_road} ({terrain_from}→{terrain_to}) "
                  f"движение {moves}→{moves_after} цена={row['cost']}", flush=True)

        try:
            signal.setitimer(signal.ITIMER_REAL, 30)
            obs, _reward, term, trunc, info = env.step(None)
            signal.setitimer(signal.ITIMER_REAL, 0)
        except Exception as exc:  # noqa: BLE001
            signal.setitimer(signal.ITIMER_REAL, 0)
            print(f"  конец хода {turn} не прошёл: {type(exc).__name__}", flush=True)
            break
        if term or trunc:
            print(f"  матч завершён на ходу {turn}", flush=True)
            break

    with open(args.out + ".done", "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"rows": len(rows)}, ensure_ascii=False))
    print(f"\nстрок записано: {len(rows)} → {args.out}", flush=True)
    print(f"дорог на карте было: {road_tiles}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
