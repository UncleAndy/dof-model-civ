"""Проверка: уходят ли поселенцы от города на реальной игре (текущие настройки, пункты 1–2).

По каждому ходу для каждого своего поселенца печатает его дистанцию до ближайшего своего города.
Если дистанция монотонно растёт — поселенец уходит; если топчется около 1–3 — не уходит.
Дополнительно фиксирует, на какой дистанции основан новый город.
"""
from __future__ import annotations

import os
import sys
import math
from pathlib import Path

os.environ["PYTHONWARNINGS"] = "ignore"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gymnasium  # noqa: E402
import civrealm  # noqa: E402,F401
from civrealm.configs import fc_args  # noqa: E402

from baselines import wedges  # noqa: E402
from brain.v2.agent import Agent  # noqa: E402
from brain.v2.calculus import dof_of  # noqa: E402

STORE = os.environ.get("V2_STORE", str(ROOT / "knowledge" / "world.json"))
TURNS = int(os.environ.get("V2_TURNS", "30"))
SEED = int(os.environ.get("V2_SEED", "9148"))
PORT = int(os.environ.get("V2_PORT", "6306"))


def main() -> int:
    fc_args["client_port"] = PORT
    agent = Agent(STORE, trace_path=ROOT / "knowledge" / "traces_probe_leave.jsonl",
                  avoid=wedges.is_wedged)
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=PORT, seed=SEED)
    try:
        own_id = env.get_playerid() or 0
    except Exception:  # noqa: BLE001
        own_id = 0
    used: set = set()
    n_cities_prev = 0
    try:
        for _ in range(TURNS):
            for _ in range(400):
                act = agent.decide(obs, info, own_id, used)
                if act is None:
                    break
                used.add(act)
                obs, _r, term, trunc, info = env.step(act)
                agent.record_outcome(obs, own_id)
                if term or trunc:
                    break
            g = agent.store.graph
            xsize = int((g.world or {}).get("xsize") or 0)
            own_cities = [c for c in g.by_kind("city") if c.is_own and c.attrs.get("x") is not None]
            # основан ли новый город
            if len(own_cities) > n_cities_prev:
                for c in own_cities:
                    pass
                n_cities_prev = len(own_cities)
            # поселенцы и их дистанция
            setts = []
            for u in g.by_kind("unit"):
                if not u.is_own or u.name != "Settlers" or u.attrs.get("x") is None:
                    continue
                dmin = None
                for c in own_cities:
                    dxc = abs((c.attrs["x"] - u.attrs["x"] + xsize // 2) % xsize - xsize // 2)
                    dyc = abs(c.attrs["y"] - u.attrs["y"])
                    d = math.sqrt(dxc * dxc + dyc * dyc)
                    if dmin is None or d < dmin:
                        dmin = d
                setts.append(f"{u.eid}@({u.attrs['x']},{u.attrs['y']})d={dmin:.1f}")
            turn = (info or {}).get('turn')
            print(f"ход {turn}: городов={len(own_cities)} [{', '.join(c.eid for c in own_cities)}] "
                  f"| поселенцы: {', '.join(setts) if setts else 'нет'}", flush=True)
            obs, _r, term, trunc, info = env.step(None)
            agent.record_outcome(obs, own_id)
            used.clear()
            if term or trunc:
                break
    finally:
        try:
            env.close()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())