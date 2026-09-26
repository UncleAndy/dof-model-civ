#!/usr/bin/env python3
"""Measure the REAL ΔDoF of individual actions (delta calibration).

The bridge projects DoF changes heuristically (fortify +0.02, goto +0.01, ...).
This script measures what actually happens: it snapshots per-entity DoF, performs
one action, re-extracts, and prints the index change plus the entities that moved.
The result is the empirical calibration table the bridge should use instead of
guesses.

Usage: .venv/bin/python scripts/measure_action_delta.py [--max-actions 12]
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

_p = argparse.ArgumentParser()
_p.add_argument("--max-actions", type=int, default=12)
_p.add_argument("--wanted", default="fortify,goto_0,build_city,set_sci_lux_tax,"
                                    "change_gov,research_tech,keep_activity,road")
_ARGS, _rest = _p.parse_known_args()
sys.argv = [sys.argv[0]] + _rest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gymnasium
from civrealm.configs import fc_args
from civrealm.freeciv.utils.port_utils import Ports

from env.entity_extractor import GameStateExtractor, compute_total_dof_index

WANTED = [w.strip() for w in _ARGS.wanted.split(",") if w.strip()]


def snapshot(extractor, obs, info, turn):
    result = extractor.extract(obs, info, turn)
    dofs = {k: e.current_dof for k, e in result.state.entities.items()}
    return result, dofs, compute_total_dof_index(result.state)


def main() -> int:
    port = Ports.get()
    print(f"slot: {port}")
    fc_args["client_port"] = port

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=port)
    extractor = GameStateExtractor(my_player_id=0)

    _, before, index_before = snapshot(extractor, obs, info, info.get("turn", 1))
    print(f"turn={info.get('turn')} entities={len(before)} index={index_before:.4f}\n")

    # Measure each distinct action once; unit actions first (that is where the
    # index actually moves), and match on prefixes so "road" != "Railroad".
    measured: set = set()
    done = 0
    attempts = 0
    ctrl_order = ("unit", "city", "gov", "dipl", "tech", "player")

    while done < _ARGS.max_actions and attempts < 400:
        attempts += 1
        avail = info.get("available_actions") or {}
        chosen = None
        for ctrl_type in ctrl_order:
            for actor_id, actions in (avail.get(ctrl_type) or {}).items():
                for name, params in actions.items():
                    if not params or (ctrl_type, name) in measured:
                        continue
                    if not any(name.startswith(w) for w in WANTED):
                        continue
                    chosen = (ctrl_type, actor_id, name)
                    break
                if chosen:
                    break
            if chosen:
                break

        if chosen is None:
            obs, _r, term, trunc, info = env.step(None)
            if term or trunc:
                print("(game ended while looking for the next action)")
                break
            _, before, index_before = snapshot(
                extractor, obs, info, info.get("turn", 1))
            continue

        ctrl_type, actor_id, name = chosen
        measured.add((ctrl_type, name))

        obs2, _r, term, trunc, info2 = env.step(chosen)
        _, after, index_after = snapshot(extractor, obs2, info2, info2.get("turn", 1))

        changed = [
            (k, before.get(k), after.get(k))
            for k in set(before) | set(after)
            if abs(after.get(k, 0.0) - before.get(k, 0.0)) > 1e-9
        ]
        print(f"{ctrl_type}/{actor_id}/{name}:  Δindex={index_after - index_before:+.4f}  "
              f"entities {len(before)}->{len(after)}")
        for k, b, a in sorted(changed,
                              key=lambda x: abs((x[2] or 0.0) - (x[1] or 0.0)),
                              reverse=True)[:4]:
            print(f"      {k}: {'absent' if b is None else f'{b:.4f}'}"
                  f" -> {'absent' if a is None else f'{a:.4f}'}")

        before, index_before = after, index_after
        obs, info = obs2, info2
        done += 1
        if term or trunc:
            print("(game ended)")
            break

    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())