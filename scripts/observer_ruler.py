#!/usr/bin/env python3
"""Всевидящая линейка: читать мир БЕЗ ожидания хода (наблюдатель ходов не получает).

Зачем отдельный путь чтения (§13.129). Штатный путь клиента привязан к ходу:
`get_info_and_observation()` зовёт `_get_info()`, который ждёт пакет начала хода, а `_get_observation()`
отдаёт состояние через `turn_manager`. У наблюдателя ходов не бывает, поэтому первый же таймаут его
убивает (`No begin_turn_packet`). Здесь мир читается из **собственных кэшей клиента** (`players`,
`cities`, `units`, карта) — их мир наполняет сам, без всякого хода, и у глобального наблюдателя они
содержат всю карту, а не только свой уголок под туманом.

Порядок обязателен: наблюдатель входит ПЕРВЫМ, в свежую партию (§13.128) — в созданную на N мест
партию N+1-го не пускают.

    .venv/bin/python scripts/observer_ruler.py --slot 6300 --aifill 0 --minp 6 --minutes 14
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import signal
import sys
import time
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _parse_cli(argv):
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--minutes", type=float, default=14.0)
    p.add_argument("--poll", type=float, default=20.0)
    p.add_argument("--reset-timeout", type=int, default=580)
    p.add_argument("--out", default=None, help="куда писать снимки (jsonl)")
    args, rest = p.parse_known_args(argv)
    sys.argv = [sys.argv[0]] + rest       # остальное — civrealm, он читает sys.argv
    return args


ARGS = _parse_cli(sys.argv[1:])

import gymnasium  # noqa: E402
from civrealm.configs import fc_args  # noqa: E402
from civrealm.freeciv.utils.port_utils import Ports  # noqa: E402


class _Timeout(Exception):
    pass


def _guard(seconds, fn, *a, **kw):
    def _on_alarm(signum, frame):
        raise _Timeout("бюджет времени исчерпан")
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn(*a, **kw)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def _find(ctl, *words):
    """Найти у контроллера держателя состояния по словам в имени (защитно)."""
    for name in dir(ctl):
        low = name.lower()
        if all(w in low for w in words) and not name.startswith("__"):
            obj = getattr(ctl, name, None)
            if obj is not None:
                return name, obj
    return None, None


def _layer(holder, *names):
    """Достать словарь-слой у держателя (units/cities/players/map)."""
    for n in names:
        layer = getattr(holder, n, None)
        if isinstance(layer, dict):
            return layer
    return {}


def _owner(item):
    if not isinstance(item, dict):
        return None
    for key in ("owner", "player", "owner_id", "player_id", "nation"):
        if item.get(key) is not None:
            return item[key]
    return None


def _snapshot(ctl, ctl_names: dict) -> dict:
    """Снимок мира из кэшей клиента — без ходового ожидания."""
    players = _layer(ctl_names.get("player"), "players") or {}
    cities = _layer(ctl_names.get("city"), "cities", "city_list") or {}
    units = _layer(ctl_names.get("unit"), "units", "unit_list") or {}
    map_holder = ctl_names.get("map")
    tiles = _layer(map_holder, "map", "tiles", "tile_list") if map_holder else {}

    def per_owner(layer):
        out: dict = {}
        for item in layer.values():
            o = _owner(item)
            if o is not None:
                out[str(o)] = out.get(str(o), 0) + 1
        return out

    known_tiles = 0
    for t in tiles.values():
        if isinstance(t, dict) and (t.get("known") or t.get("seen") or t.get("visible")):
            known_tiles += 1

    roster = {}
    for pid, pdata in players.items():
        if isinstance(pdata, dict):
            roster[str(pid)] = {
                "name": pdata.get("name") or pdata.get("username"),
                "score": pdata.get("score"),
                "alive": pdata.get("is_alive", pdata.get("alive")),
            }

    return {
        "players": len(players),
        "roster": roster,
        "cities": len(cities),
        "units": len(units),
        "tiles_known": known_tiles,
        "tiles_total": len(tiles),
        "cities_by_owner": per_owner(cities),
        "units_by_owner": per_owner(units),
    }


def main() -> int:
    print("=" * 96)
    print("ВСЕВИДЯЩАЯ ЛИНЕЙКА: чтение мира без хода (наблюдатель)")
    print("=" * 96)
    port = ARGS.slot or _guard(45, Ports.get)
    fc_args["client_port"] = port
    print(f"  слот {port}  aifill={fc_args.get('aifill')!r}  minp={fc_args.get('minp')!r}  "
          f"имя {fc_args.get('username')!r}")

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = _guard(ARGS.reset_timeout, env.reset, client_port=port)
    ctl = env.unwrapped.civ_controller
    clstate = getattr(ctl, "clstate", None)
    print(f"  вошли: игрок {getattr(getattr(ctl, 'player_ctrl', None), 'my_player_id', None)!r}, "
          f"ход {info.get('turn')!r}")

    # Вход в глобальный наблюдатель штатным путём библиотеки.
    if clstate is not None and hasattr(clstate, "observe"):
        clstate.observe()
        print(f"  наблюдение включено (состояние {getattr(clstate, 'observing', '?')!r})")

    # Кто у контроллера держит слои — ищем по именам, а не по догадке.
    ctl_names = {}
    for key, words in (("player", ("player", "ctrl")), ("city", ("city", "ctrl")),
                       ("unit", ("unit", "ctrl")), ("map", ("map", "ctrl"))):
        name, obj = _find(ctl, *words)
        ctl_names[key] = obj
        print(f"  слой {key}: держатель {name!r}")

    out_path = pathlib.Path(ARGS.out) if ARGS.out else None
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(out_path, "a", encoding="utf-8") if out_path else None

    deadline = time.time() + max(1.0, ARGS.minutes) * 60
    shots = 0
    while time.time() < deadline:
        time.sleep(ARGS.poll)
        shot = {"at": time.strftime("%H:%M:%S")}
        try:
            shot.update(_snapshot(ctl, ctl_names))
        except Exception as exc:  # noqa: BLE001
            shot["error"] = repr(exc)
        shots += 1
        print(f"  [{shot['at']}] игроков {shot.get('players')}  городов {shot.get('cities')} "
              f"({shot.get('cities_by_owner')})  юнитов {shot.get('units')} "
              f"({shot.get('units_by_owner')})  клеток известно {shot.get('tiles_known')}"
              f"/{shot.get('tiles_total')}")
        if handle:
            handle.write(json.dumps(shot, ensure_ascii=False) + "\n")
            handle.flush()

    if handle:
        handle.close()
        print(f"\n  снимки: {out_path} ({shots} шт.)")
    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
