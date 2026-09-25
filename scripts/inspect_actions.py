#!/usr/bin/env python3
"""Inspect the real `available_actions` structure from live CivRealm games.

Diagnostic only: opens one game on an auto-allocated slot, dumps the shape of
the action space per turn to tests/fixtures/real_actions.json, and prints a
summary. Grounds the DOF action bridge in observed data.

Usage:
    .venv/bin/python scripts/inspect_actions.py --turns 8
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

# Resolve our CLI before civrealm's own argparse runs over sys.argv.
_p = argparse.ArgumentParser()
_p.add_argument("--turns", type=int, default=8)
_p.add_argument("--out", default="tests/fixtures/real_actions.json")
_p.add_argument("--fixture-out", default="tests/fixtures/real_available_actions.json")
_ARGS, _rest = _p.parse_known_args()
sys.argv = [sys.argv[0]] + _rest

import gymnasium
from civrealm.configs import fc_args

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def trim_available(avail: dict, max_actors: int = 2, max_actions: int = 8) -> dict:
    """Keep a small but faithful slice of a real action space.

    Types are preserved: actor keys stay int/str exactly as civrealm emits
    them, and both valid (truthy params) and invalid (empty params) actions are
    kept so tests can assert the filter behaviour on real vocabulary.
    """
    trimmed: dict = {}
    for ctrl_type, actors in avail.items():
        kept_actors: dict = {}
        for actor_id, actions in list(actors.items())[:max_actors]:
            # keep the first few of each kind so both branches are covered
            valid = [(n, p) for n, p in actions.items() if p]
            invalid = [(n, p) for n, p in actions.items() if not p]
            picked = valid[:max_actions] + invalid[:max_actions]
            if picked:
                kept_actors[actor_id] = dict(picked)
        if kept_actors:
            trimmed[ctrl_type] = kept_actors
    return trimmed


def describe(avail: dict) -> dict:
    """Summarise one turn's action space."""
    summary = {}
    for ctrl_type, actors in avail.items():
        n_actions = with_params = 0
        param_keys: dict[str, int] = {}
        samples: dict[str, object] = {}
        actor_key_types: set[str] = set()
        for actor_id, actions in actors.items():
            actor_key_types.add(type(actor_id).__name__)
            for name, params in actions.items():
                n_actions += 1
                if params:
                    with_params += 1
                    if isinstance(params, dict):
                        for k in params:
                            param_keys[k] = param_keys.get(k, 0) + 1
                    if len(samples) < 6:
                        samples[name] = params if not isinstance(params, dict) \
                            else {k: repr(v)[:40] for k, v in list(params.items())[:4]}
        summary[ctrl_type] = {
            "actor_key_types": sorted(actor_key_types),
            "n_actors": len(actors),
            "n_actions": n_actions,
            "n_valid": with_params,
            "param_keys": dict(sorted(param_keys.items(), key=lambda kv: -kv[1])[:10]),
            "valid_samples": samples,
        }
    return summary


def main() -> int:
    from civrealm.freeciv.utils.port_utils import Ports

    port = Ports.get()
    print(f"slot: {port}")

    fc_args["client_port"] = port
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=port)

    dump: list[dict] = []
    fixture: dict | None = None
    for _ in range(_ARGS.turns):
        avail = info.get("available_actions", {})
        turn = info.get("turn")
        summary = describe(avail)
        dump.append({"turn": turn, "controllers": summary})

        if fixture is None and avail:
            fixture = trim_available(avail)

        print(f"\n=== turn {turn}")
        for ctrl, s in summary.items():
            print(f"  {ctrl:<8} actors={s['n_actors']:<4} ({','.join(s['actor_key_types'])}) "
                  f"actions={s['n_actions']:<5} valid={s['n_valid']:<4} params={s['param_keys']}")
            for name, params in list(s["valid_samples"].items())[:3]:
                print(f"      {name}: {params}")

        # pick any valid action to advance the turn
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
            print("  no valid action found; ending")
            break
        obs, _r, term, trunc, info = env.step(action)
        if term or trunc:
            print("  game ended")
            break

    env.close()

    out = os.path.join(ROOT, _ARGS.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(dump, fh, indent=2)
    print(f"\nsaved action-space dump -> {out}")

    if fixture:
        fx = os.path.join(ROOT, _ARGS.fixture_out)
        os.makedirs(os.path.dirname(fx), exist_ok=True)
        with open(fx, "w") as fh:
            json.dump(fixture, fh, indent=2)
        print(f"saved real action fixture -> {fx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())