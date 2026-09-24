#!/usr/bin/env python3
"""
Capture real CivRealm observations for testing.

Connects to a running Freeciv-web Docker container via Gym API,
plays a few turns with a random agent, and saves observations to JSON.

Usage:
    .venv/bin/python scripts/capture_obs.py --turns 10 --output tests/fixtures/real_obs_01.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure the project root is on the path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(description="Capture real CivRealm observations")
    parser.add_argument("--turns", type=int, default=10, help="Number of turns to play")
    parser.add_argument(
        "--output",
        type=str,
        default="tests/fixtures/real_obs_01.json",
        help="Output JSON file path",
    )
    parser.add_argument("--port", type=int, default=6001, help="Client port")
    args = parser.parse_args()

    # Import CivRealm
    try:
        import gymnasium
        from civrealm.configs import fc_args
        from civrealm.agents import RandomAgent
    except ImportError as e:
        print(f"ERROR: Cannot import CivRealm: {e}")
        print("Make sure CivRealm is installed: pip install -e civrealm")
        sys.exit(1)

    # Connect to the game
    print(f"==> Connecting to Freeciv-web (port {args.port})...")
    fc_args['client_port'] = args.port

    try:
        env = gymnasium.make('civrealm/FreecivBase-v0')
    except Exception as e:
        print(f"ERROR: Cannot connect to Freeciv-web: {e}")
        print("Make sure Freeciv-web Docker is running:")
        print("  docker compose -f civrealm/src/civrealm/configs/docker-compose.yaml up -d")
        sys.exit(1)

    agent = RandomAgent()
    observations, info = env.reset(client_port=args.port)

    captured = []

    print(f"--> Playing {args.turns} turns...")
    for step in range(args.turns):
        action = agent.act(observations, info)
        next_obs, reward, terminated, truncated, next_info = env.step(action)

        # Deep-copy and serialize (convert numpy arrays to lists)
        snapshot = {
            "step": step,
            "turn": info.get("turn", step),
            "observation": _serialize(observations),
            "info": _sanitize_info(info),
            "action": _serialize_action(action),
            "reward": reward,
            "terminated": terminated,
            "truncated": truncated,
        }
        captured.append(snapshot)

        observations = next_obs
        info = next_info

        if terminated or truncated:
            break

    env.close()

    # Save
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(captured, f, indent=2, sort_keys=True, default=str)

    print(f"--> Saved {len(captured)} observations to {output_path}")
    print(f"--> Last turn: {captured[-1]['turn']}")
    print(f"--> Entities in last snapshot:")
    last_obs = captured[-1]["observation"]
    for entity_type, entities in last_obs.items():
        print(f"    {entity_type}: {len(entities)} entities")


def _serialize(obj):
    """Convert numpy arrays and other non-serializable objects."""
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    elif hasattr(obj, "tolist"):
        return obj.tolist()
    elif hasattr(obj, "item"):
        return obj.item()
    return obj


def _sanitize_info(info: dict) -> dict:
    """Make info dict JSON-serializable."""
    result = {}
    for k, v in info.items():
        if k == "available_actions":
            # Convert to simple dict structure
            result[k] = {
                ctrl_type: {
                    str(actor_id): list(actions.keys())
                    for actor_id, actions in actors.items()
                }
                for ctrl_type, actors in v.items()
            }
        else:
            result[k] = _serialize(v)
    return result


def _serialize_action(action):
    """Serialize action tuple."""
    if action is None:
        return None
    return list(action)


if __name__ == "__main__":
    main()
