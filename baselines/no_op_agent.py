#!/usr/bin/env python3
"""
NoOp baseline agent: does nothing (returns None every turn).
Used as a lower-bound baseline for comparison.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from civrealm.agents import BaseAgent


class NoOpAgent(BaseAgent):
    """Agent that always returns None (no action)."""

    def act(self, observations, info):
        return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="NoOp baseline agent")
    parser.add_argument("--port", type=int, default=6001, help="Client port")
    parser.add_argument("--turns", type=int, default=100, help="Max turns")
    parser.add_argument("--output", type=str, help="Save log to JSON")
    args = parser.parse_args()

    from civrealm.configs import fc_args
    fc_args['client_port'] = args.port

    try:
        import gymnasium
        env = gymnasium.make('civrealm/FreecivBase-v0')
    except Exception as e:
        print(f"ERROR: Cannot connect to Freeciv-web: {e}", file=sys.stderr)
        sys.exit(1)

    agent = NoOpAgent()
    observations, info = env.reset(client_port=args.port)

    done = False
    step = 0
    total_reward = 0

    while not done and step < args.turns:
        action = agent.act(observations, info)
        observations, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        done = terminated or truncated
        step += 1

    env.close()

    print(f"NoOp agent finished after {step} steps")
    print(f"Total reward: {total_reward}")
    print(f"Final turn: {info.get('turn', 'unknown')}")


if __name__ == "__main__":
    main()
