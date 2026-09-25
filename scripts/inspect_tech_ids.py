#!/usr/bin/env python3
"""Check whether tech action names can be mapped onto extractor tech entities.

`research_tech_Alphabet_2` may carry the tech id as a trailing integer, which
would let a research action attach its DoF delta to `tech_<id>`. Verify on live
data before relying on it.

Usage: .venv/bin/python scripts/inspect_tech_ids.py
"""
from __future__ import annotations

import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
sys.argv = ["x"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gymnasium
from civrealm.configs import fc_args
from civrealm.freeciv.utils.port_utils import Ports

from env.entity_extractor import GameStateExtractor


def main() -> int:
    port = Ports.get()
    print(f"slot: {port}")
    fc_args["client_port"] = port

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=port)

    extractor = GameStateExtractor(my_player_id=0)
    result = extractor.extract(obs, info, info.get("turn", 0))
    entities = result.state.entities

    tech_entities = sorted(k for k in entities if k.startswith("tech_"))
    print(f"\ntech entities ({len(tech_entities)}): {tech_entities[:15]}")

    actions = list(info.get("available_actions", {}).get("tech", {}).get("cur_player", {}))
    print(f"\ntech actions ({len(actions)}), first 12:")
    for name in actions[:12]:
        params = info["available_actions"]["tech"]["cur_player"][name]
        match = re.search(r"_(\d+)$", name)
        target = f"tech_{match.group(1)}" if match else None
        exists = target in entities if target else None
        print(f"  {name!r:55} valid={bool(params)!s:5} trailing_id={match.group(1) if match else None}"
              f" -> {target} exists={exists}")

    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())