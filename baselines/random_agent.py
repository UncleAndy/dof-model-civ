#!/usr/bin/env python3
"""
Random agent for CivRealm — baseline for comparison.
Uses CivRealm's built-in RandomAgent with DoF tracking.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import gymnasium


def main():
    parser = argparse.ArgumentParser(description="Random baseline agent")
    parser.add_argument("--port", type=int, default=6001, help="Client port")
    parser.add_argument("--turns", type=int, default=100, help="Max turns")
    parser.add_argument("--output", type=str, help="Save observations to JSON")
    args = parser.parse_args()

    try:
        from civrealm.configs import fc_args
        from civrealm.agents import RandomAgent
    except ImportError:
        print("ERROR: CivRealm not installed. Run: pip install -e civrealm", file=sys.stderr)
        sys.exit(1)

    fc_args['client_port'] = args.port

    try:
        env = gymnasium.make('civrealm/FreecivBase-v0')
    except Exception as e:
        print(f"ERROR: Cannot connect to Freeciv-web: {e}", file=sys.stderr)
        sys.exit(1)

    from env.entity_extractor import GameStateExtractor
    from env.config import CONFIG

    agent = RandomAgent()
    extractor = GameStateExtractor(my_player_id=CONFIG.my_player_id)

    observations, info = env.reset(client_port=args.port)
    done = False
    step = 0

    turn_log = []

    while not done and step < args.turns:
        try:
            action = agent.act(observations, info)
            dof_state = extractor.extract(observations, info, info.get("turn", step))

            turn_log.append({
                "step": step,
                "turn": info.get("turn", step),
                "action": str(action),
                "entity_count": len(dof_state.state.entities),
                "psi_digest": dof_state.state.psi.get("digest", ""),
            })

            observations, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            step += 1
        except Exception as e:
            print(f"Error at step {step}: {e}", file=sys.stderr)
            break

    env.close()

    print(f"Game ended after {step} steps")
    print(f"Final turn: {info.get('turn', 'unknown')}")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(turn_log, f, indent=2)
        print(f"Saved log to {args.output}")


if __name__ == "__main__":
    main()
