#!/usr/bin/env python3
"""Всевидящая линейка: можно ли мерить ВСЮ карту и ВСЕХ игроков без тумана.

Владелец требует считать результат по всем игрокам и всей карте. Записи сторон
этого не дают: под туманом каждая сторона видит ~22 клетки из всей карты
(§13.126). Поэтому проверяется внешний канал — **глобальный наблюдатель**:
клиент библиотеки умеет войти наблюдателем (`/observe` — обзор всей карты), и
тогда мир отдаёт ему чужое состояние без тумана.

Проба обязана быть СРАВНИТЕЛЬНОЙ: «туман поднялся» и «в наблюдении и так всё
было» выглядят одинаково. Поэтому обзор мерится ДВАЖДЫ — до входа в наблюдение
и после, — и печатается разница. Если разницы нет, вывод «наблюдатель видит всю
карту» был бы ложным.

    .venv/bin/python scripts/probe_observer.py --slot 6000 --turns 4
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import signal
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _parse_cli(argv):
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--turns", type=int, default=4)
    p.add_argument("--slot", type=int, default=6000,
                   help="слот с уже идущей игрой (наблюдателя пускают в живую партию)")
    p.add_argument("--reset-timeout", type=int, default=300)
    p.add_argument("--out", default=None, help="куда сложить снимки обзора")
    p.add_argument("--poll", type=float, default=0.0,
                   help="снимать обзор по часам (секунды между снимками), а не шагами хода")
    p.add_argument("--minutes", type=float, default=0.0,
                   help="сколько минут снимать обзор в режиме часов")
    args, rest = p.parse_known_args(argv)
    sys.argv = [sys.argv[0]] + rest   # остальное — civrealm (он читает sys.argv)
    return args


ARGS = _parse_cli(sys.argv[1:])

import gymnasium  # noqa: E402
from civrealm.configs import fc_args  # noqa: E402


class ProbeTimeout(Exception):
    pass


def _guard(seconds, fn, *a, **kw):
    def _on_alarm(signum, frame):
        raise ProbeTimeout("бюджет времени пробы исчерпан")
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn(*a, **kw)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def _view(obs: dict) -> dict:
    """Что видно в наблюдении: сколько объектов и какая доля проходима видна."""
    out = {}
    for key in ("unit", "city", "tile", "player", "diplomacy", "tech"):
        layer = obs.get(key)
        out[key] = len(layer) if isinstance(layer, dict) else 0
    tiles = obs.get("tile") or {}
    if isinstance(tiles, dict) and tiles:
        visible = 0
        known = 0
        owners = set()
        for t in tiles.values():
            if not isinstance(t, dict):
                continue
            if t.get("visible"):
                visible += 1
            if t.get("known") or t.get("visible"):
                known += 1
            if t.get("owner") is not None:
                owners.add(t["owner"])
        out["tile_visible"] = visible
        out["tile_known"] = known
        out["tile_owners"] = sorted(owners)
    for key in ("unit", "city"):
        layer = obs.get(key) or {}
        owners = set()
        if isinstance(layer, dict):
            for item in layer.values():
                if isinstance(item, dict) and item.get("owner") is not None:
                    owners.add(item["owner"])
        out[f"{key}_owners"] = sorted(owners)
    players = obs.get("player") or obs.get("players") or {}
    out["players"] = sorted(players.keys()) if isinstance(players, dict) else []
    return out


def main() -> int:
    print("=" * 96)
    print("ВСЕВИДЯЩАЯ ЛИНЕЙКА: поднимает ли наблюдение туман")
    print("=" * 96)
    print(f"  слот: {ARGS.slot}   имя: {fc_args.get('username')!r}   "
          f"aifill={fc_args.get('aifill')!r}  minp={fc_args.get('minp')!r}")

    fc_args["client_port"] = ARGS.slot
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = _guard(ARGS.reset_timeout, env.reset, client_port=ARGS.slot)

    ctl = getattr(env.unwrapped, "civ_controller", None)
    pctl = getattr(ctl, "player_ctrl", None)
    # Наблюдение живёт НЕ у player_ctrl, а у состояния клиента: контроллер держит
    # его как `clstate` (CivController.clstate = ClientState(...)).
    clstate = getattr(ctl, "clstate", None)
    print(f"  наш игрок: {getattr(pctl, 'my_player_id', None)!r}   "
          f"ход: {info.get('turn')!r}   "
          f"клиентское состояние: {type(clstate).__name__ if clstate is not None else 'нет'}")

    snapshots = []
    before = _view(obs)
    snapshots.append({"stage": "до наблюдения", "turn": info.get("turn"), **before})
    print(f"\n  ДО наблюдения: клеток видно {before.get('tile_visible')}, "
          f"известно {before.get('tile_known')}, чужих владельцев "
          f"{sorted(set(before.get('unit_owners', []) + before.get('city_owners', [])))}")
    print(f"     слой: юнитов {before['unit']}, городов {before['city']}, "
          f"клеток {before['tile']}, игроков {before['player']}")

    # Вход в глобальный наблюдатель — тот самый штатный путь библиотеки.
    entered = False
    try:
        if clstate is not None and hasattr(clstate, "observe"):
            clstate.observe()
            entered = True
            print("  наблюдение: отправлена команда наблюдения (обзор всей карты); "
                  f"состояние наблюдения клиента: {getattr(clstate, 'observing', '?')!r}")
        else:
            print("  [!] у клиентского состояния нет метода наблюдения")
    except Exception as exc:  # noqa: BLE001
        print(f"  [!] вход в наблюдение не удался: {exc!r}")

    if entered:
        try:
            _guard(30, lambda: __import__("time").sleep(6))
            obs2 = ctl.get_info_and_observation()[1] if hasattr(ctl, "get_info_and_observation") else obs
            after = _view(obs2)
            snapshots.append({"stage": "после наблюдения", "turn": info.get("turn"), **after})
            print(f"\n  ПОСЛЕ наблюдения: клеток видно {after.get('tile_visible')}, "
                  f"известно {after.get('tile_known')}, чужих владельцев "
                  f"{sorted(set(after.get('unit_owners', []) + after.get('city_owners', [])))}")
            print(f"     слой: юнитов {after['unit']}, городов {after['city']}, "
                  f"клеток {after['tile']}, игроков {after['player']}")
            dv = (after.get("tile_visible") or 0) - (before.get("tile_visible") or 0)
            dk = (after.get("tile_known") or 0) - (before.get("tile_known") or 0)
            print(f"\n  РАЗНИЦА: видно +{dv}, известно +{dk}")
            if dv > 0 or dk > 0 or len(after.get("unit_owners") or []) > len(before.get("unit_owners") or []):
                print("ВЫВОД: наблюдение РАСШИРЯЕТ обзор — всевидящая линейка работает.")
            else:
                print("ВЫВОД: обзор НЕ расширился — либо команда не сработала, либо игра "
                      "не отдаёт наблюдателю больше (проверять по ходам, а не по одному снимку).")
        except Exception as exc:  # noqa: BLE001
            print(f"  [!] снимок после наблюдения не получен: {exc!r}")

    # Режим часов: у наблюдателя нет своего хода, поэтому мир не «шагается», а
    # опрашивается — сервер сам присылает состояние каждый ход. Иначе снимок
    # пришлось бы делать шагами хода, которых у наблюдателя не бывает.
    if ARGS.poll > 0:
        import time as _time
        deadline = _time.time() + max(1.0, ARGS.minutes) * 60
        empty_streak = 0
        print(f"\n  режим часов: опрос каждые {ARGS.poll} с, "
              f"{ARGS.minutes} мин (мир может стартовать позже)")
        while _time.time() < deadline:
            _time.sleep(ARGS.poll)
            try:
                info2, obs2 = ctl.get_info_and_observation()
            except Exception as exc:  # noqa: BLE001
                print(f"    [!] опрос не удался: {exc!r}")
                empty_streak += 1
                if empty_streak >= 4:
                    print("  мир не отвечает — прекращаю опрос")
                    break
                continue
            view = _view(obs2)
            snapshots.append({"stage": f"опрос (ход {info2.get('turn')})",
                              "turn": info2.get("turn"), **view})
            foreign = sorted(set(view.get("unit_owners", []) + view.get("city_owners", []))
                             - {getattr(pctl, "my_player_id", None)})
            print(f"    ход {info2.get('turn')}: игроков {view['player']}, "
                  f"юнитов {view['unit']}, городов {view['city']}, "
                  f"чужих владельцев {foreign}")
            empty_streak = 0
        if ARGS.out:
            path = pathlib.Path(ARGS.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(snapshots, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            print(f"\n  снимки обзора сохранены: {path}")
        try:
            env.close()
        except Exception:  # noqa: BLE001
            pass
        return 0

    # Прогон по ходам: как ведёт себя обзор дальше.
    print(f"\n  ходов на наблюдение: {ARGS.turns}")
    for step in range(ARGS.turns * 4):
        try:
            obs, _r, terminated, truncated, info = _guard(60, env.step, None)
        except Exception as exc:  # noqa: BLE001
            print(f"  [!] шаг не удался: {exc!r}")
            break
        view = _view(obs)
        snapshots.append({"stage": f"ход {info.get('turn')}", "turn": info.get("turn"), **view})
        print(f"    ход {info.get('turn')}: видно {view.get('tile_visible')} клеток, "
              f"юнитов {view['unit']}, городов {view['city']}, "
              f"чужие владельцы {sorted(set(view.get('unit_owners', []) + view.get('city_owners', [])))}")
        if terminated or truncated:
            print("  игра завершилась досрочно")
            break

    if ARGS.out:
        path = pathlib.Path(ARGS.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshots, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"\n  снимки обзора сохранены: {path}")
    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
