#!/usr/bin/env python3
"""Do turns actually advance for each agent type?

`civ_controller.perform_action()` ends the turn ONLY when the action is None:
a real action never advances the turn. So an agent that always finds something
to do plays the entire match inside turn 1, while an agent that returns None lets
the game (and the AI opponents) run. This probe shows the turn progression per
agent type — the artefact that made `no-op` look best.

Usage: .venv/bin/python scripts/inspect_turn_per_agent.py [steps]
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

_p = argparse.ArgumentParser()
_p.add_argument("--steps", type=int, default=12)
_p.add_argument("--agents", default="no-op,dof_defensive,random")
_ARGS, _rest = _p.parse_known_args()
sys.argv = [sys.argv[0]] + _rest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import importlib.util

import gymnasium
from civrealm.configs import fc_args
from civrealm.freeciv.utils.port_utils import Ports

from env.entity_extractor import GameStateExtractor

spec = importlib.util.spec_from_file_location(
    "dof_runner", os.path.join(ROOT, "baselines", "run_real_tournament.py")
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def run(agent_type: str, steps: int) -> None:
    port = Ports.get()
    fc_args["client_port"] = port
    extractor = GameStateExtractor(my_player_id=0)
    agent = runner.build_agent(agent_type, extractor)

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=port)

    timeline = []
    for _ in range(steps):
        action = agent.act(obs, info)
        obs, _r, term, trunc, info = env.step(action)
        timeline.append((info.get("turn"), "end-turn" if action is None else action[2]))
        if term or trunc:
            break
    env.close()

    turns = [t for t, _ in timeline]
    print(f"\n{agent_type}: slot={port} steps={len(timeline)} "
          f"turns seen={sorted(set(turns))} final_turn={turns[-1] if turns else None}")
    for turn, what in timeline:
        print(f"   turn={turn}  {what}")


def main() -> int:
    for agent_type in [a.strip() for a in _ARGS.agents.split(",") if a.strip()]:
        run(agent_type, _ARGS.steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())