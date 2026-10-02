"""Пробник: почему штраф перенаселённости не срабатывает в живом прогоне.

Каждый ход печатает: есть ли у графа rules (border_city_radius_sq), сколько своих городов с
координатами, и для каждого своего юнита — штраф перенаселённости.

Запуск: V2_TURNS=10 V2_SEED=9148 V2_PORT=6301 python scripts/v2_probe_crowd.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["PYTHONWARNINGS"] = "ignore"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gymnasium  # noqa: E402
import civrealm  # noqa: E402,F401
from civrealm.configs import fc_args  # noqa: E402

from baselines import wedges  # noqa: E402
from brain.v2.agent import Agent  # noqa: E402
from brain.v2.horizon import city_crowding_penalty  # noqa: E402

STORE = os.environ.get("V2_STORE", str(ROOT / "knowledge" / "world.json"))
TURNS = int(os.environ.get("V2_TURNS", "10"))
SEED = int(os.environ.get("V2_SEED", "9148"))
PORT = int(os.environ.get("V2_PORT", "6301"))


def main() -> int:
    fc_args["client_port"] = PORT
    agent = Agent(STORE, trace_path=ROOT / "knowledge" / "traces_probe_crowd.jsonl",
                  avoid=wedges.is_wedged)
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=PORT, seed=SEED)
    try:
        own_id = env.get_playerid() or 0
    except Exception:  # noqa: BLE001
        own_id = 0
    used: set = set()
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
            r = g.rules or {}
            own_cities = [c for c in g.by_kind("city") if c.is_own and c.attrs.get("x") is not None]
            units = [u for u in g.by_kind("unit") if u.is_own and u.attrs.get("x") is not None]
            crowd = []
            for s in units:
                p, _w = city_crowding_penalty(g, s.eid.split(":")[1])
                crowd.append((s.eid, s.name, s.attrs["x"], s.attrs["y"], round(p, 3)))
            print(f"ход {(info or {}).get('turn')}: rules.border={r.get('border_city_radius_sq')!r} "
                  f"| своих_городов {len(own_cities)} "
                  f"[{[(c.eid, c.attrs['x'], c.attrs['y']) for c in own_cities]}] | "
                  f"юниты {crowd}", flush=True)
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