#!/usr/bin/env python3
"""
DOF-Core agent for CivRealm.

Combines:
- GameStateExtractor (game state → SystemState)
- ActionOptionGenerator (SystemState → candidate actions)
- HeuristicGenerator (strategy-based filtering)
- DOFCalculusCore (Rust — selects best action)
- ActionMapper (DOF action → CivRealm action)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import gymnasium

from civrealm.configs import fc_args
from civrealm.agents import BaseAgent

from env.entity_extractor import GameStateExtractor
from env.action_mapper import ActionOptionGenerator, CivAction
from brain.generator.heuristics import ALL_STRATEGIES, DEFENSIVE, HeuristicGenerator
from env.config import CONFIG


class DOFAgent(BaseAgent):
    """
    Agent that uses DOF-Core to select actions.
    """

    def __init__(self, strategy: str = "defensive", port: int = 6001):
        super().__init__()
        self.port = port
        self.extractor = GameStateExtractor(my_player_id=0)
        self.action_generator = ActionOptionGenerator()
        self.strategy_name = strategy

        # Select strategy
        strategy_map = {s.name: s for s in ALL_STRATEGIES}
        self.strategy = strategy_map.get(strategy, DEFENSIVE)
        self.heuristic_gen = HeuristicGenerator(strategy=self.strategy)

        # Try to import Rust core
        try:
            from dof_core import DOFCalculusCore, CoreEntity, CoreAction
            self.core = DOFCalculusCore(lookahead_horizon=3, context_switch_penalty=0.5)
            self.use_rust = True
        except ImportError:
            print("Warning: Rust core not available, using Python fallback")
            self.use_rust = False

        self.turn = 0
        self.step_count = 0

    def act(self, observations, info):
        """
        Select the best action using DOF-Core.
        """
        self.step_count += 1
        turn = info.get("turn", self.step_count)

        # Step 1: Extract DOF state from observations
        result = self.extractor.extract(observations, info, turn)
        state = result.state

        # Step 2: Get available actions from CivRealm
        available_actions = info.get("available_actions", {})

        # Step 3: Generate ActionOption candidates
        candidates = self.action_generator.generate_from_state(state, available_actions)

        if not candidates:
            return None

        # Step 4: Filter by strategy
        candidates = self.heuristic_gen.generate_candidates(state, available_actions)

        if not candidates:
            return None

        # Step 5: Select best action
        if self.use_rust:
            best_action = self._select_with_rust(state, candidates)
        else:
            best_action = self.heuristic_gen.select_best(candidates, state)

        if best_action is None:
            return None

        # Step 6: Convert DOF action to CivRealm action
        return self._map_to_civrealm(best_action, available_actions)

    def _select_with_rust(self, state, candidates):
        """Use Rust core to select the best action."""
        from dof_core import CoreEntity, CoreAction

        # Convert state to CoreEntity list
        core_entities = [
            CoreEntity(
                entity_id=e.entity_id,
                current_dof=e.current_dof,
                is_collapse_source=e.is_collapse_source,
                is_reversible=e.time_to_collapse_mks < 1e14,
            )
            for e in state.entities.values()
        ]

        # Convert candidates to CoreAction list
        core_actions = [
            CoreAction(
                action_id=c["option_id"],
                description=c.get("description", ""),
                dof_delta=list(c.get("projected_dof_delta", {}).items()),
                is_reversible=c.get("is_reversible", True),
                duration_turns=c.get("estimated_duration_mks", 5_000_000) / 5_000_000,
            )
            for c in candidates
        ]

        # Call Rust core
        decision = self.core.select_best(core_entities, core_actions)

        if decision.chosen_action_id is None:
            return None

        # Find the selected candidate
        for c in candidates:
            if c["option_id"] == decision.chosen_action_id:
                return c

        return None

    def _map_to_civrealm(self, dof_action: dict, available_actions: dict):
        """Convert DOF action dict to CivRealm action tuple."""
        action_id = dof_action["option_id"]

        # Parse action_id: "{ctrl_type}_{actor_id}_{action_name}"
        parts = action_id.split("_", 2)
        if len(parts) < 3:
            return None

        ctrl_type = parts[0]
        actor_id = parts[1]
        action_name = parts[2]

        # Check if action is available
        if ctrl_type not in available_actions:
            return None

        # Find actor
        actors = available_actions[ctrl_type]
        if actor_id not in actors:
            # Try first available actor
            if actors:
                actor_id = next(iter(actors))
            else:
                return None

        # Check if action exists for this actor
        actions = actors[actor_id]
        if action_name not in actions:
            # Try first available action
            if actions:
                action_name = next(iter(actions))
            else:
                return None

        return (ctrl_type, int(actor_id), action_name)


def main():
    parser = argparse.ArgumentParser(description="DOF-Core agent")
    parser.add_argument("--port", type=int, default=6001, help="Client port")
    parser.add_argument("--turns", type=int, default=100, help="Max turns")
    parser.add_argument("--strategy", default="defensive", choices=[s.name for s in ALL_STRATEGIES])
    parser.add_argument("--output", type=str, help="Save log to JSON")
    args = parser.parse_args()

    fc_args['client_port'] = args.port

    try:
        env = gymnasium.make('civrealm/FreecivBase-v0')
    except Exception as e:
        print(f"ERROR: Cannot connect to Freeciv-web: {e}", file=sys.stderr)
        sys.exit(1)

    agent = DOFAgent(strategy=args.strategy, port=args.port)
    observations, info = env.reset(client_port=args.port)

    done = False
    step = 0
    turn_log = []

    while not done and step < args.turns:
        try:
            action = agent.act(observations, info)

            # Track DoF state
            dof_state = agent.extractor.extract(observations, info, info.get("turn", step))
            turn_log.append({
                "step": step,
                "turn": info.get("turn", step),
                "action": str(action) if action else None,
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

    print(f"DOF agent finished after {step} steps")
    print(f"Final turn: {info.get('turn', 'unknown')}")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(turn_log, f, indent=2)
        print(f"Saved log to {args.output}")


if __name__ == "__main__":
    main()
