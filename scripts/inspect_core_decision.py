#!/usr/bin/env python3
"""Inspect a real DOF-Core decision on a live CivRealm state.

Prints the core's root index, the net delta and veto flag of each candidate, and
which one it picked (or why it declined to act). Diagnostic for warm-up turns
where the agent unexpectedly skips every action.

Usage: .venv/bin/python scripts/inspect_core_decision.py
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

_p = argparse.ArgumentParser()
_p.add_argument("--top", type=int, default=8)
_p.add_argument("--turns", type=int, default=3)
_ARGS, _rest = _p.parse_known_args()
sys.argv = [sys.argv[0]] + _rest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gymnasium
from civrealm.configs import fc_args

from dof_core import CoreAction, CoreEntity, DOFCalculusCore
from env.entity_extractor import GameStateExtractor, compute_total_dof_index
from env.action_mapper import ActionOptionGenerator
from brain.generator.heuristics import ALL_STRATEGIES, HeuristicGenerator


def main() -> int:
    from civrealm.freeciv.utils.port_utils import Ports

    port = Ports.get()
    print(f"slot: {port}")
    fc_args["client_port"] = port

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=port)

    extractor = GameStateExtractor(my_player_id=0)
    core = DOFCalculusCore()
    gen = HeuristicGenerator(strategy=next(s for s in ALL_STRATEGIES if s.name == "expansionist"))

    for step in range(_ARGS.turns):
        result = extractor.extract(obs, info, info.get("turn", step))
        state = result.state
        avail = info.get("available_actions", {})

        cands = gen.generate_candidates(state, avail)
        root_index = compute_total_dof_index(state)

        print(f"\n=== turn {info.get('turn')} | entities={len(state.entities)} "
              f"| candidates={len(cands)} | spec index={root_index:.4f}")

        if cands:
            deltas = [sum(c["projected_dof_delta"].values()) for c in cands]
            print(f"  candidate raw deltas: min={min(deltas):+.3f} max={max(deltas):+.3f} "
                  f"nonzero={sum(1 for d in deltas if d)}")

            ents = [
                CoreEntity(entity_id=e.entity_id, current_dof=e.current_dof,
                           is_collapse_source=e.is_collapse_source,
                           is_reversible=e.time_to_collapse_mks > 1e14)
                for e in state.entities.values()
            ]
            acts = [
                CoreAction(action_id=c["option_id"], description=c.get("description", ""),
                           dof_delta=list(c["projected_dof_delta"].items()),
                           is_reversible=bool(c["is_reversible"]), duration_turns=1.0)
                for c in cands
            ]
            decision = core.select_best(ents, acts)
            print(f"  core: chosen={decision.chosen_action_id} net_delta={decision.net_delta:.4f}")
            audit = sorted(decision.audit, key=lambda a: a[1], reverse=True)
            for action_id, score, vetoed in audit[:_ARGS.top]:
                print(f"     {score:+.4f} vetoed={vetoed!s:5} {action_id}")

        action = None
        for ctrl_type, actors in avail.items():
            for actor_id, actions in actors.items():
                for name, params in actions.items():
                    if params:
                        action = (ctrl_type, actor_id, name)
                        break
                if action:
                    break
            if action:
                break
        if action is None:
            print("  (no valid action to advance with)")
            break
        obs, _r, term, trunc, info = env.step(action)
        if term or trunc:
            print("  game ended")
            break

    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())