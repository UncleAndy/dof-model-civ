#!/usr/bin/env python3
"""
Analyze tournament results and generate comparison plots with confidence intervals.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))


def plot_tournament_results(results_file: str, output_file: str = "tournament_results.png"):
    """Generate comparison plots from tournament results."""
    with open(results_file) as f:
        data = json.load(f)

    agents = list(data.keys())

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle("DOF-MODEL-CIV: Agent Comparison", fontsize=14)

    # Plot 1: Average DoF Index per agent (with std)
    ax = axes[0, 0]
    agent_means = []
    agent_stds = []
    for agent in agents:
        episodes = data[agent]
        avg_dofs = [ep["avg_dof"] for ep in episodes]
        agent_means.append(sum(avg_dofs) / len(avg_dofs))
        agent_stds.append((sum((x - sum(avg_dofs)/len(avg_dofs))**2 for x in avg_dofs) / len(avg_dofs))**0.5)

    bars = ax.bar(range(len(agents)), agent_means, yerr=agent_stds, capsize=5, alpha=0.7)
    ax.set_xticks(range(len(agents)))
    ax.set_xticklabels([a.replace("dof_", "") for a in agents], rotation=45, ha='right', fontsize=8)
    ax.set_title("Avg DoF Index (±std)")
    ax.set_ylabel("DoF")

    # Plot 2: Min/Max Entities with range
    ax = axes[0, 1]
    for i, agent in enumerate(agents):
        episodes = data[agent]
        min_ent = [ep["min_entities"] for ep in episodes]
        max_ent = [ep["max_entities"] for ep in episodes]
        mean_min = sum(min_ent) / len(min_ent)
        mean_max = sum(max_ent) / len(max_ent)
        ax.bar(i, mean_max - mean_min, bottom=mean_min, alpha=0.7, label=agent.replace("dof_", ""))
    ax.set_title("Entity Count Range")
    ax.set_xlabel("Agent")
    ax.set_ylabel("Entities")
    ax.set_xticks(range(len(agents)))
    ax.set_xticklabels([a.replace("dof_", "") for a in agents], rotation=45, ha='right', fontsize=8)

    # Plot 3: Irreversible Actions Ratio
    ax = axes[0, 2]
    for i, agent in enumerate(agents):
        episodes = data[agent]
        irr_ratios = [ep["irreversible_ratio"] for ep in episodes]
        mean_irr = sum(irr_ratios) / len(irr_ratios)
        std_irr = (sum((x - mean_irr)**2 for x in irr_ratios) / len(irr_ratios))**0.5
        ax.bar(i, mean_irr, yerr=std_irr, capsize=5, alpha=0.7)
    ax.set_title("Irreversible Actions Ratio (±std)")
    ax.set_xlabel("Agent")
    ax.set_ylabel("Ratio")
    ax.set_xticks(range(len(agents)))
    ax.set_xticklabels([a.replace("dof_", "") for a in agents], rotation=45, ha='right', fontsize=8)

    # Plot 4: DoF over episodes (time series)
    ax = axes[1, 0]
    for agent in agents:
        episodes = data[agent]
        avg_dofs = [ep["avg_dof"] for ep in episodes]
        ax.plot(range(len(avg_dofs)), avg_dofs, marker='o', label=agent.replace("dof_", ""))
    ax.set_title("Avg DoF over Episodes")
    ax.set_xlabel("Episode")
    ax.set_ylabel("Avg DoF")
    ax.legend(fontsize=8)

    # Plot 5: Cumulative DoF (area under curve)
    ax = axes[1, 1]
    for agent in agents:
        episodes = data[agent]
        avg_dofs = [ep["avg_dof"] for ep in episodes]
        cumulative = [sum(avg_dofs[:i+1]) for i in range(len(avg_dofs))]
        ax.plot(range(len(cumulative)), cumulative, marker='s', label=agent.replace("dof_", ""))
    ax.set_title("Cumulative DoF")
    ax.set_xlabel("Episode")
    ax.set_ylabel("Cumulative DoF")
    ax.legend(fontsize=8)

    # Plot 6: Turns Played
    ax = axes[1, 2]
    for agent in agents:
        episodes = data[agent]
        turns = [ep["turns"] for ep in episodes]
        ax.plot(range(len(turns)), turns, marker='^', label=agent.replace("dof_", ""))
    ax.set_title("Turns Played")
    ax.set_xlabel("Episode")
    ax.set_ylabel("Turns")
    ax.legend(fontsize=8)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    print(f"Saved plot to {output_file}")

    # Print summary statistics
    print("\n" + "=" * 70)
    print("SUMMARY STATISTICS")
    print("=" * 70)
    print(f"{'Agent':<20} {'AvgDoF':>10} {'±Std':>8} {'IrrRat':>10} {'Turns':>8}")
    print("-" * 70)

    for agent in agents:
        episodes = data[agent]
        avg_dofs = [ep["avg_dof"] for ep in episodes]
        irr_ratios = [ep["irreversible_ratio"] for ep in episodes]
        turns = [ep["turns"] for ep in episodes]

        mean_dof = sum(avg_dofs) / len(avg_dofs)
        std_dof = (sum((x - mean_dof)**2 for x in avg_dofs) / len(avg_dofs))**0.5
        mean_irr = sum(irr_ratios) / len(irr_ratios)
        mean_turns = sum(turns) / len(turns)

        print(f"{agent:<20} {mean_dof:>10.3f} {std_dof:>8.3f} {mean_irr:>10.3f} {mean_turns:>8.1f}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("results_file", help="Path to tournament results JSON")
    parser.add_argument("--output", default="tournament_results.png")
    args = parser.parse_args()

    plot_tournament_results(args.results_file, args.output)


if __name__ == "__main__":
    main()
