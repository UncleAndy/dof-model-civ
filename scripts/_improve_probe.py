"""Живой замер: остаётся ли irrigation в меню, пока рабочий его выполняет.

Держим рабочего на irrigation несколько ходов и КАЖДЫЙ ход печатаем: есть ли действие в меню,
что в наблюдении изменилось (extras/еда города). Сторож на каждый шаг, чтобы не висеть.

Запуск: python scripts/_improve_probe.py <port> <seed> [turns]
"""
from __future__ import annotations

import json
import signal
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "civrealm" / "src"))

import gymnasium  # noqa: E402
import civrealm  # noqa: E402,F401
from civrealm.configs import fc_args  # noqa: E402

from brain.v2 import sensors  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 6330
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 9240
TURNS = int(sys.argv[3]) if len(sys.argv) > 3 else 20
WANT = ("irrigation", "mine", "cultivate", "build_road", "road", "plant")


class Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise Timeout()


signal.signal(signal.SIGALRM, _alarm)


def step(env, action):
    signal.setitimer(signal.ITIMER_REAL, 30)
    try:
        return env.step(action)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def extras(obs):
    m = obs.get("map") or {}
    ex = m.get("extras")
    if ex is None:
        return 0
    if hasattr(ex, "tolist"):
        ex = ex.tolist()
    n = 0

    def walk(v):
        nonlocal n
        if isinstance(v, list):
            for x in v:
                walk(x)
        elif v:
            n += 1

    walk(ex)
    return n


def food(obs, own):
    out = {}
    for cid, c in (obs.get("city") or {}).items():
        if isinstance(c, dict) and c.get("owner") == own:
            out[cid] = (c.get("size"), c.get("surplus_food"))
    return out


fc_args["client_port"] = PORT
env = gymnasium.make("civrealm/FreecivBase-v0")
obs, info = env.reset(client_port=PORT, seed=SEED)
own = env.get_playerid() or 0
print(f"own_id={own}", flush=True)

held = None          # (aid, action)
for turn in range(TURNS):
    menu = sensors.read_menu((info or {}).get("available_actions") or {})
    ex = extras(obs)
    fd = food(obs, own)
    if held:
        aid, act = held
        opts = sensors.valid_options(menu, "unit", str(aid))
        print(f"[ход {turn}] держим unit/{aid}/{act}: в меню сейчас "
              f"{'ЕСТЬ' if act in opts else 'НЕТ'}; extras={ex}; еда={fd}", flush=True)
    # ищем рабочего с работой
    if held is None:
        for a in sensors.read_actors(obs):
            if a.owner != own:
                continue
            opts = sensors.valid_options(menu, "unit", str(a.aid))
            hits = [o for o in opts if o in WANT]
            if hits:
                held = (a.aid, hits[0])
                print(f"[ход {turn}] НАЧИНАЮ unit/{a.aid}/{hits[0]} тип={a.type_name} "
                      f"({a.x},{a.y}); extras={ex}; еда={fd}", flush=True)
                break
    acted = False
    if held:
        try:
            step(env, ("unit", int(held[0]), held[1]))
            acted = True
        except Timeout:
            print("  таймаут действия", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  действие не принято: {e}", flush=True)
    if not acted:
        for a in sensors.read_actors(obs):
            if a.owner != own:
                continue
            opts = sensors.valid_options(menu, "unit", str(a.aid))
            pick = next((o for o in ("keep_activity", "fortify", "goto_0") if o in opts), None)
            if pick:
                try:
                    step(env, ("unit", int(a.aid), pick))
                except Exception:  # noqa: BLE001
                    pass
    try:
        obs, _r, term, trunc, info = step(env, None)
    except Timeout:
        print("  таймаут закрытия хода", flush=True)
        break
    if term or trunc:
        print("партия окончилась", flush=True)
        break

print("ГОТОВО", flush=True)
try:
    env.close()
except Exception:  # noqa: BLE001
    pass