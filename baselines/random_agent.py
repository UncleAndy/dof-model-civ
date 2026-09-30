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

    agent = RandomAgent()

    def _seen(obs) -> dict[str, int]:
        """Сколько сущностей каждого вида видно — прямо из наблюдения.

        Раньше это считал экстрактор v1; в v2 прибор не должен зависеть от модели, поэтому
        берём размеры секций наблюдения как есть (это факт мира, а не вывод модели).
        """
        out: dict[str, int] = {}
        for key in ('unit', 'city', 'tech', 'dipl', 'gov', 'player'):
            section = (obs or {}).get(key)
            if hasattr(section, '__len__'):
                out[key] = len(section)
        return out

    observations, info = env.reset(client_port=args.port)
    done = False
    step = 0

    turn_log = []

    while not done and step < args.turns:
        try:
            action = agent.act(observations, info)

            turn_log.append({
                "step": step,
                "turn": info.get("turn", step),
                "action": str(action),
                "seen": _seen(observations),
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
