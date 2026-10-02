"""Пробник простоя: почему у юнитов нет цели движения.

Каждый ход печатает: сколько своих юнитов видно и у скольких есть координаты, размер раскрытой
области, сколько целей `explore` построено и у скольких юнитов `unrevealed_near` вернул «нет».

Запуск: V2_TURNS=25 V2_SEED=9148 V2_PORT=6300 python scripts/v2_probe_idle.py
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
from brain.v2 import explore as explore_mod  # noqa: E402
from brain.v2 import generator, sensors  # noqa: E402
from brain.v2.agent import Agent  # noqa: E402

STORE = os.environ.get("V2_STORE", str(ROOT / "knowledge" / "world.json"))
TURNS = int(os.environ.get("V2_TURNS", "25"))
SEED = int(os.environ.get("V2_SEED", "9148"))
PORT = int(os.environ.get("V2_PORT", "6300"))


def main() -> int:
    fc_args["client_port"] = PORT
    agent = Agent(STORE, trace_path=ROOT / "knowledge" / "traces_probe_idle.jsonl",
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
            own_units = [u for u in g.by_kind("unit") if u.is_own]
            with_xy = [u for u in own_units if u.attrs.get("x") is not None]
            no_frontier = 0
            for u in with_xy:
                if explore_mod.unrevealed_near(g, u.attrs["x"], u.attrs["y"]) is None:
                    no_frontier += 1
            menu = sensors.read_menu((info or {}).get("available_actions") or {})
            goals = generator.derive_goals(g, menu)
            n_explore = sum(1 for x in goals if x.get("goal") == "explore")
            paths, open_goals = generator.generate(g, menu, own_id, avoid=agent.avoid)
            n_paths_explore = sum(1 for p in paths if p.goal == "explore")
            # сколько своих юнитов вообще имеют законные направления движения
            with_moves = 0
            for u in with_xy:
                aid = u.eid.split(":")[1]
                opts = [o for o in sensors.valid_options(menu, "unit", aid)
                        if str(o).startswith("goto_")]
                if opts:
                    with_moves += 1
            cov = len(explore_mod.covered(g))
            w = g.world or {}
            print(f"ход {(info or {}).get('turn')}: своих_юнитов {len(own_units)}, с_координатами "
                  f"{len(with_xy)}, без_фронтира {no_frontier}, покрытие {cov}/"
                  f"{int(w.get('xsize') or 0) * int(w.get('ysize') or 0)}, "
                  f"целей_explore {n_explore}, путей_explore {n_paths_explore}, "
                  f"с_ходом {with_moves}",
                  flush=True)
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