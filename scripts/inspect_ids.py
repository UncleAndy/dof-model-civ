#!/usr/bin/env python3
"""Check that extractor entity ids match civrealm actor ids.

If they do not correspond, ``estimate_dof_delta`` can never attach a projected
delta to an entity, every candidate looks DoF-neutral, and the selection
degenerates to no-op-like actions. That is a silent failure, so it gets its own
diagnostic.

Usage: .venv/bin/python scripts/inspect_ids.py
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

_p = argparse.ArgumentParser()
_p.add_argument("--turns", type=int, default=1)
_ARGS, _rest = _p.parse_known_args()
sys.argv = [sys.argv[0]] + _rest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gymnasium
from civrealm.configs import fc_args

from env.entity_extractor import GameStateExtractor
from env.action_mapper import ActionOptionGenerator


def report(label: str, entity_ids: set[str], actor_ids: set[str]) -> None:
    overlap = entity_ids & actor_ids
    print(f"  {label:<8} entities={len(entity_ids):<4} actors={len(actor_ids):<4} "
          f"overlap={len(overlap):<4} "
          f"entity-only={len(entity_ids - actor_ids):<4} "
          f"actor-only={len(actor_ids - entity_ids)}")
    if overlap:
        print(f"      shared sample: {sorted(overlap)[:6]}")
    else:
        print("      !! NO OVERLAP -> DoF deltas cannot attach to any entity")


def main() -> int:
    from civrealm.freeciv.utils.port_utils import Ports

    port = Ports.get()
    print(f"slot: {port}")
    fc_args["client_port"] = port

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=port)

    extractor = GameStateExtractor(my_player_id=0)
    mapper = ActionOptionGenerator()

    for _ in range(_ARGS.turns):
        result = extractor.extract(obs, info, info.get("turn", 0))
        entities = result.state.entities
        avail = info.get("available_actions", {})

        print(f"\n=== turn {info.get('turn')} | ctrl types: {sorted(avail)}")
        print(f"  entity ids: {list(entities)[:10]}")

        for ctrl_type in ("unit", "city"):
            entity_ids = {
                k.split("_", 1)[1] for k in entities if k.startswith(f"{ctrl_type}_")
            }
            actor_ids = {str(k) for k in avail.get(ctrl_type, {})}
            if entity_ids or actor_ids:
                report(ctrl_type, entity_ids, actor_ids)

        # Does any generated candidate carry a non-empty DoF delta?
        cands = mapper.generate_from_state(result.state, avail)
        with_delta = [c for c in cands if c["projected_dof_delta"]]
        print(f"  candidates={len(cands)}  with_projected_dof_delta={len(with_delta)}")
        for c in with_delta[:5]:
            print(f"      {c['option_id']} -> {c['projected_dof_delta']}")

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
            break
        obs, _r, term, trunc, info = env.step(action)
        if term or trunc:
            print("  game ended")
            break

    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())