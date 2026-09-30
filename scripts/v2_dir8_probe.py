"""Замер: какому смещению соответствует goto_N (dir8).

Важно (измерено): наблюдение после РЕАЛЬНОГО действия — частичное (только изменения), поэтому
позицию читаем на полном срезе ПОСЛЕ закрытия хода (`env.step(None)`). Одна проба — одна партия,
иначе юнит успевает потратить ходы.
"""
from __future__ import annotations

import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gymnasium  # noqa: E402
import civrealm  # noqa: E402,F401
from civrealm.configs import fc_args  # noqa: E402

from brain.v2 import sensors  # noqa: E402

BASE_SEED = int(os.environ.get("V2_SEED", "9020"))
PORT_BASE = int(os.environ.get("V2_PORT", "6311"))
DIRS = (0, 1, 2, 3, 4, 5, 6, 7)


def find_unit(obs, own_id):
    for a in sensors.read_actors(obs):
        if a.owner == own_id and a.type_name == "Explorer":
            return a
    own = [a for a in sensors.read_actors(obs) if a.owner == own_id]
    return own[0] if own else None


def probe(n: int) -> None:
    seed = BASE_SEED + n
    # Каждая проба — свой слот и пауза: измерено, что повторный reset на том же порту сразу
    # после закрытия партии ловит BeginTurnTimeout (сервер ещё не поднял новую).
    port = PORT_BASE + n
    time.sleep(2.0)
    fc_args["client_port"] = port
    env = gymnasium.make("civrealm/FreecivBase-v0")
    try:
        obs, info = env.reset(client_port=port, seed=seed)
        own_id = env.get_playerid() or 0
        u0 = find_unit(obs, own_id)
        if u0 is None:
            print(f"  goto_{n}: своего юнита нет")
            return
        x0, y0 = u0.x, u0.y
        menu = sensors.read_menu((info or {}).get("available_actions") or {})
        if f"goto_{n}" not in sensors.valid_options(menu, "unit", str(u0.aid)):
            print(f"  goto_{n}: не предложено миром")
            return
        env.step(("unit", int(u0.aid), f"goto_{n}"))
        obs, _r, term, trunc, info = env.step(None)      # закрываем ход -> полный срез
        u1 = (obs.get("unit") or {}).get(str(u0.aid)) or {}
        x1, y1 = u1.get("x"), u1.get("y")
        if x1 is None:
            u2 = find_unit(obs, own_id)
            x1, y1 = (u2.x, u2.y) if u2 else (None, None)
        if x1 is None:
            print(f"  goto_{n}: позиция недоступна")
            return
        print(f"  goto_{n}: ({x0},{y0}) -> ({x1},{y1})   dx={x1 - x0} dy={y1 - y0}")
    finally:
        try:
            env.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    print(f"порты {PORT_BASE}..{PORT_BASE + max(DIRS)}, сиды {BASE_SEED}.."
          f"{BASE_SEED + max(DIRS)} (одна проба = одна партия)")
    for n in DIRS:
        probe(n)
    print("\nнапоминание: X замыкается (цилиндр), поэтому dx может выглядеть «через край»")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())