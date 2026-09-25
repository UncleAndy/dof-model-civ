#!/usr/bin/env python3
"""
Tournament runner: compare DOF agent vs random baseline.
Now uses unique seeds per agent for variability.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from dataclasses import dataclass, field
import hashlib

sys.path.insert(0, str(Path(__file__).parent.parent))

from env.entity_extractor import GameStateExtractor
from env.action_mapper import ActionOptionGenerator
from brain.generator.heuristics import ALL_STRATEGIES, DEFENSIVE, HeuristicGenerator


@dataclass
class MatchResult:
    """Results from a single match."""
    agent_name: str = ""
    turns_played: int = 0
    total_dof_index_series: list[float] = field(default_factory=list)
    entity_count_series: list[int] = field(default_factory=list)
    collapse_count: int = 0
    irreversible_actions: int = 0
    total_actions: int = 0
    final_score: float = 0.0  # agent-specific performance score

    @property
    def avg_dof_index(self) -> float:
        if not self.total_dof_index_series:
            return 0.0
        return sum(self.total_dof_index_series) / len(self.total_dof_index_series)

    @property
    def min_entity_count(self) -> int:
        return min(self.entity_count_series) if self.entity_count_series else 0

    @property
    def max_entity_count(self) -> int:
        return max(self.entity_count_series) if self.entity_count_series else 0

    @property
    def irreversible_ratio(self) -> float:
        if self.total_actions == 0:
            return 0.0
        return self.irreversible_actions / self.total_actions


def run_match(agent_type: str, turns: int = 100, seed: int = 42) -> MatchResult:
    """
    Run a single match with unique seed per agent.
    """
    extractor = GameStateExtractor(my_player_id=0)
    action_gen = ActionOptionGenerator()

    if agent_type == "random":
        agent = None
    else:
        strategy_name = agent_type.replace("dof_", "") if agent_type.startswith("dof_") else "defensive"
        strategy_map = {s.name: s for s in ALL_STRATEGIES}
        strategy = strategy_map.get(strategy_name, DEFENSIVE)
        agent = HeuristicGenerator(strategy=strategy)

    result = MatchResult(agent_name=agent_type)

    for turn in range(turns):
        # Unique seed per agent per turn
        turn_seed = seed + hash(agent_type) % 10000 + turn
        obs = _generate_observations(turn, turn_seed)
        info = _generate_info(turn, turn_seed)

        dof_result = extractor.extract(obs, info, turn)
        state = dof_result.state

        candidates = action_gen.generate_from_state(state, info.get("available_actions", {}))
        if not candidates:
            break

        if agent_type == "random":
            import random
            action = random.choice(candidates)
        else:
            candidates = agent.generate_candidates(state, info.get("available_actions", {}))
            if not candidates:
                break
            action = agent.select_best(candidates, state)
            if action is None:
                break

        # Track metrics
        non_collapse = [e for e in state.entities.values() if not e.is_collapse_source]
        if non_collapse:
            result.total_dof_index_series.append(
                sum(e.current_dof for e in non_collapse) / len(non_collapse)
            )
        result.entity_count_series.append(len(state.entities))
        result.total_actions += 1

        if not action.get("is_reversible", True):
            result.irreversible_actions += 1

    result.turns_played = len(result.total_dof_index_series)
    result.final_score = sum(result.total_dof_index_series)
    return result


def _generate_observations(turn: int, seed: int) -> dict:
    """Generate synthetic observations with unique seed."""
    import random
    random.seed(seed)

    num_cities = min(1 + turn // 10, 5)
    num_units = min(2 + turn // 5, 15)
    num_techs = min(3 + turn // 3, 20)

    obs = {"city": {}, "unit": {}, "tech": {}, "dipl": {}}

    for i in range(num_cities):
        obs["city"][str(i)] = {
            "population": random.randint(1, 8),
            "food": random.randint(-2, 10),
            "production": random.randint(3, 20),
            "gold": random.randint(10, 60),
            "happiness": random.randint(-1, 5),
            "defense": random.randint(0, 3),
            "prod_process": random.randint(0, 15),
        }

    for i in range(num_units):
        obs["unit"][str(100 + i)] = {
            "type_rule_name": random.choice(["Warrior", "Worker", "Settler", "Knight"]),
            "health": random.randint(20, 100),
            "moves_left": random.randint(0, 3),
            "max_moves": random.randint(1, 3),
        }

    for i in range(num_techs):
        obs["tech"][str(i)] = {
            "name": random.choice(["Bronze Working", "Writing", "Mathematics", "Iron Working"]),
            "progress": random.randint(0, 100),
            "prerequisites_met": random.randint(0, 3),
            "total_prerequisites": random.randint(1, 4),
        }

    for i in range(1, 4):
        obs["dipl"][str(i)] = {
            "relationship": random.uniform(-1, 1),
            "alliance_options": [],
            "trade_options": ["gold", "tech"][:random.randint(0, 2)],
        }

    return obs


def _generate_info(turn: int, seed: int) -> dict:
    """Generate synthetic info."""
    import random
    random.seed(seed + 1000)

    return {
        "turn": turn,
        "available_actions": {
            "unit": {
                str(100 + i): {
                    "goto_0": True,
                    "goto_1": True,
                    "fortify": True,
                    "attack": random.random() > 0.7,
                }
                for i in range(min(2 + turn // 5, 15))
            },
            "city": {
                str(i): {
                    "build_unit": True,
                    "build_improvement": True,
                    "research_tech": True,
                }
                for i in range(min(1 + turn // 10, 5))
            },
        },
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run tournament")
    parser.add_argument("--episodes", type=int, default=10, help="Number of episodes per agent")
    parser.add_argument("--turns", type=int, default=100, help="Max turns per episode")
    parser.add_argument("--output", type=str, help="Output JSON file")
    args = parser.parse_args()

    agents = ["random"] + [f"dof_{s.name}" for s in ALL_STRATEGIES]
    results = {agent: [] for agent in agents}

    print(f"Running tournament: {len(agents)} agents × {args.episodes} episodes × {args.turns} turns")

    for agent in agents:
        print(f"\n  {agent}...", end="", flush=True)
        for ep in range(args.episodes):
            # Unique seed per episode (varies by agent and episode)
            seed = hash(agent) + ep * 1000 + 42
            result = run_match(agent, turns=args.turns, seed=seed)
            results[agent].append(result)
            print(".", end="", flush=True)

    print("\n\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"{'Agent':<20} {'Turns':>6} {'AvgDoF':>8} {'MinEnt':>7} {'MaxEnt':>7} {'IrrRat':>7}")
    print("-" * 70)

    for agent in agents:
        avg_turns = sum(r.turns_played for r in results[agent]) / len(results[agent])
        avg_dof = sum(r.avg_dof_index for r in results[agent]) / len(results[agent])
        min_ent = min(r.min_entity_count for r in results[agent])
        max_ent = max(r.max_entity_count for r in results[agent])
        irr_ratio = sum(r.irreversible_ratio for r in results[agent]) / len(results[agent])

        print(f"{agent:<20} {avg_turns:>6.1f} {avg_dof:>8.3f} {min_ent:>7} {max_ent:>7} {irr_ratio:>7.2f}")

    if args.output:
        try:
            output_data = {
                agent: [
                    {
                        "turns": r.turns_played,
                        "avg_dof": r.avg_dof_index,
                        "min_entities": r.min_entity_count,
                        "max_entities": r.max_entity_count,
                        "irreversible_ratio": r.irreversible_ratio,
                        "final_score": r.final_score,
                    }
                    for r in results[agent]
                ]
                for agent in agents
            }
            with open(args.output, "w") as f:
                json.dump(output_data, f, indent=2)
            print(f"\nSaved to {args.output} ({Path(args.output).absolute()})")
        except Exception as e:
            print(f"\nError saving to {args.output}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
