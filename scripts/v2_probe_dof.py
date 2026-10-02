"""Пробник: снижается ли DoF поселенца по близости к своему городу (пункты 1–2, §10.108).

Каждый ход для каждого своего юнита печатает: eid, тип, координаты, дистанцию до ближайшего своего
города, итоговый DoF (через dof_of, уже с множителем) и ln(DoF). Поселенцы рядом с городом должны
иметь DoF заметно ниже 27.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["PYTHONWARNINGS"] = "ignore"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import math  # noqa: E402
import gymnasium  # noqa: E402
import civrealm  # noqa: E402,F401
from civrealm.configs import fc_args  # noqa: E402

from baselines import wedges  # noqa: E402
from brain.v2.agent import Agent  # noqa: E402
from brain.v2.calculus import dof_of  # noqa: E402

STORE = os.environ.get("V2_STORE", str(ROOT / "knowledge" / "world.json"))
TURNS = int(os.environ.get("V2_TURNS", "10"))
SEED = int(os.environ.get("V2_SEED", "9148"))
PORT = int(os.environ.get("V2_PORT", "6305"))


def main() -> int:
    fc_args["client_port"] = PORT
    agent = Agent(STORE, trace_path=ROOT / "knowledge" / "traces_probe_dof.jsonl",
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
            xsize = int((g.world or {}).get("xsize") or 0)
            own_cities = [c for c in g.by_kind("city") if c.is_own and c.attrs.get("x") is not None]
            rows = []
            for u in g.by_kind("unit"):
                if not u.is_own or u.attrs.get("x") is None:
                    continue
                dmin = None
                for c in own_cities:
                    dxc = abs((c.attrs["x"] - u.attrs["x"] + xsize // 2) % xsize - xsize // 2)
                    dyc = abs(c.attrs["y"] - u.attrs["y"])
                    d = math.sqrt(dxc * dxc + dyc * dyc)
                    if dmin is None or d < dmin:
                        dmin = d
                v, origin = dof_of(g, u)
                rows.append((u.name or "?", round(dmin, 1) if dmin is not None else None,
                             round(v, 2) if v else None, origin.split(";")[-1].strip() if v else ""))
            print(f"ход {(info or {}).get('turn')}: " +
                  " | ".join(f"{n}@{d}->DoF{v} ({o})" for n, d, v, o in rows), flush=True)
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