#!/usr/bin/env python3
"""
Real CivRealm tournament runner with progress and suppressed warnings.
"""
from __future__ import annotations

import json
import sys
import os
import warnings
from pathlib import Path
from dataclasses import dataclass, field

# Suppress ALL warnings
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

sys.path.insert(0, str(Path(__file__).parent.parent))

import gymnasium
from civrealm.configs import fc_args
from civrealm.agents import RandomAgent, BaseAgent

from env.entity_extractor import GameStateExtractor
from env.action_mapper import ActionOptionGenerator
from brain.generator.heuristics import ALL_STRATEGIES, DEFENSIVE, HeuristicGenerator


class NoOpAgent(BaseAgent):
    def act(self, observations, info):
        return None


@dataclass
class MatchResult:
    """Results from a single real match."""
    agent_name: str = ""
    turns_played: int = 0
    total_dof_index_series: list[float] = field(default_factory=list)
    entity_count_series: list[int] = field(default_factory=list)
    irreversible_actions: int = 0
    total_actions: int = 0
    final_turn: int = 0
    error: str = ""

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


def run_real_match(agent_type: str, turns: int = 100, port: int = 6001) -> MatchResult:
    """Run a real match against CivRealm."""
    result = MatchResult(agent_type=agent_type)

    try:
        # Create agent
        if agent_type == "random":
            agent = RandomAgent()
        elif agent_type == "no-op":
            agent = NoOpAgent()
        elif agent_type.startswith("dof_"):
            strategy_name = agent_type.replace("dof_", "")
            strategy_map = {s.name: s for s in ALL_STRATEGIES}
            strategy = strategy_map.get(strategy_name, DEFENSIVE)
            gen = HeuristicGenerator(strategy=strategy)

            class RealDOFAgent(BaseAgent):
                def __init__(self, gen):
                    super().__init__()
                    self.extractor = GameStateExtractor(my_player_id=0)
                    self.action_gen = ActionOptionGenerator()
                    self.gen = gen
                    self.use_rust = False
                    try:
                        from dof_core import DOFCalculusCore, CoreEntity, CoreAction
                        self.core = DOFCalculusCore(lookahead_horizon=3, context_switch_penalty=0.5)
                        self.use_rust = True
                    except ImportError:
                        pass

                def act(self, observations, info):
                    turn = info.get("turn", 0)
                    dof_result = self.extractor.extract(observations, info, turn)
                    state = dof_result.state
                    available = info.get("available_actions", {})
                    candidates = self.action_gen.generate_from_state(state, available)
                    if not candidates:
                        return None
                    candidates = self.gen.generate_candidates(state, available)
                    if not candidates:
                        return None

                    if self.use_rust:
                        from dof_core import CoreEntity, CoreAction
                        core_entities = [
                            CoreEntity(e.entity_id, e.current_dof, e.is_collapse_source, e.time_to_collapse_mks < 1e14)
                            for e in state.entities.values()
                        ]
                        core_actions = [
                            CoreAction(c["option_id"], c.get("description", ""),
                                       list(c.get("projected_dof_delta", {}).items()),
                                       c.get("is_reversible", True),
                                       c.get("estimated_duration_mks", 5_000_000) / 5_000_000)
                            for c in candidates
                        ]
                        decision = self.core.select_best(core_entities, core_actions)
                        if decision.chosen_action_id is None:
                            return None
                        for c in candidates:
                            if c["option_id"] == decision.chosen_action_id:
                                best = c
                                break
                        else:
                            return None
                    else:
                        best = self.gen.select_best(candidates, state)
                        if best is None:
                            return None

                    # Map to CivRealm action
                    action_id = best["option_id"]
                    parts = action_id.split("_", 2)
                    if len(parts) < 3:
                        return None
                    ctrl_type, actor_id, action_name = parts
                    if ctrl_type not in available:
                        return None
                    actors = available[ctrl_type]
                    if actor_id not in actors:
                        if actors:
                            actor_id = next(iter(actors))
                        else:
                            return None
                    actions = actors[actor_id]
                    if action_name not in actions:
                        if actions:
                            action_name = next(iter(actions))
                        else:
                            return None

                    if not best.get("is_reversible", True):
                        result.irreversible_actions += 1
                    result.total_actions += 1

                    return (ctrl_type, int(actor_id), action_name)

            agent = RealDOFAgent(gen)
        else:
            agent = RandomAgent()

        # Connect
        fc_args['client_port'] = port
        env = gymnasium.make('civrealm/FreecivBase-v0')
        observations, info = env.reset(client_port=port)

        done = False
        step = 0

        while not done and step < turns:
            try:
                action = agent.act(observations, info)

                # Track DoF state
                extractor = GameStateExtractor(my_player_id=0)
                dof_result = extractor.extract(observations, info, info.get("turn", step))
                state = dof_result.state

                non_collapse = [e for e in state.entities.values() if not e.is_collapse_source]
                if non_collapse:
                    result.total_dof_index_series.append(
                        sum(e.current_dof for e in non_collapse) / len(non_collapse)
                    )
                result.entity_count_series.append(len(state.entities))

                observations, reward, terminated, truncated, info = env.step(action)
                done = terminated or truncated
                step += 1

                # Print progress
                if step % 5 == 0:
                    print(f" [{step}/{turns}]", end="", flush=True)

            except Exception as e:
                result.error = str(e)
                break

        env.close()
        result.turns_played = step
        result.final_turn = info.get("turn", step)

    except Exception as e:
        result.error = str(e)

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run real CivRealm tournament")
    parser.add_argument("--episodes", type=int, default=3, help="Episodes per agent")
    parser.add_argument("--turns", type=int, default=100, help="Max turns per episode")
    parser.add_argument("--port", type=int, default=6001, help="Base CivRealm port")
    parser.add_argument("--output", type=str, help="Output JSON file")
    args = parser.parse_args()

    agents = ["random", "no-op"] + [f"dof_{s.name}" for s in ALL_STRATEGIES]
    results = {agent: [] for agent in agents}

    print(f"Running REAL tournament: {len(agents)} agents × {args.episodes} episodes × {args.turns} turns")
    print(f"Port range: {args.port} ~ {args.port + args.episodes - 1}")
    print("")

    for agent in agents:
        print(f"  {agent:<20}", end="", flush=True)
        for ep in range(args.episodes):
            port = args.port + ep
            result = run_real_match(agent, turns=args.turns, port=port)
            results[agent].append(result)
            if result.error:
                print(f" ERR({result.error[:30]})", end="", flush=True)
            else:
                print(f" ✓", end="", flush=True)
        print("")

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"{'Agent':<20} {'Turns':>6} {'AvgDoF':>8} {'MinEnt':>7} {'MaxEnt':>7} {'IrrRat':>7}")
    print("-" * 70)

    for agent in agents:
        avg_turns = sum(r.turns_played for r in results[agent]) / max(len(results[agent]), 1)
        avg_dof = sum(r.avg_dof_index for r in results[agent]) / max(len(results[agent]), 1)
        min_ent = min((r.min_entity_count for r in results[agent]), default=0)
        max_ent = max((r.max_entity_count for r in results[agent]), default=0)
        irr_ratio = sum(r.irreversible_ratio for r in results[agent]) / max(len(results[agent]), 1)

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
                        "error": r.error,
                    }
                    for r in results[agent]
                ]
                for agent in agents
            }
            with open(args.output, "w") as f:
                json.dump(output_data, f, indent=2)
            print(f"\nSaved to {args.output}")
        except Exception as e:
            print(f"\nError saving: {e}")


if __name__ == "__main__":
    main()
