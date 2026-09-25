#!/usr/bin/env python3
"""
Analyse real CivRealm tournament results with confidence intervals.

Reads the JSON written by baselines/run_real_tournament.py (per-episode
records) and reports, per agent:

* mean AvgDoF and FinalDoF with a 95% Student-t CI,
* mean irreversibility ratio (with the issued/skipped counts that produced it),
* for every DOF strategy: the difference against `random`, with a
  non-parametric 95% bootstrap CI and Cohen's d.

Usage:
    bash do.sh analyze [tournament_results.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics.stats import bootstrap_diff_ci, ci95, cohens_d, mean, stdev  # noqa: E402


DEFAULT_INPUT = "tournament_results.json"
DEFAULT_PLOT = "tournament_results.png"


def _series(records: list[dict], key: str) -> list[float]:
    return [float(r.get(key, 0.0) or 0.0) for r in records]


def _load(path: Path) -> tuple[dict, dict[str, list[dict]]]:
    payload = json.loads(path.read_text())
    if "results" in payload:            # current format
        return payload.get("meta", {}), payload["results"]
    # Legacy format: {agent: [episode dicts]}
    return {}, payload


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT)
    if not path.exists():
        print(f"==> No results file at {path}. Run: bash do.sh real-tournament "
              f"--episodes 15 --turns 30 --output {path}")
        return 1

    meta, results = _load(path)
    agents = list(results)

    print("=" * 96)
    print("REAL TOURNAMENT ANALYSIS — mean with 95% CI (Student t)")
    print("=" * 96)
    print("Scope: every match on this stand replays the SAME scenario (Publite2 creates")
    print("the game before the agent connects), so these intervals quantify")
    print("within-scenario replication only — not variation across environments.")
    if meta:
        print(f"episodes/agent={meta.get('episodes')}  turns/match={meta.get('turns')}  "
              f"elapsed={meta.get('elapsed_s', 0) / 60:.1f} min")
    print()
    print(f"{'Agent':<20}{'N':>4}{'Index':>10}{'95% CI':>22}"
          f"{'IrrRat':>9}{'Issued':>8}{'Skipped':>9}")
    print("-" * 96)

    index_by_agent: dict[str, list[float]] = {}
    for agent in agents:
        records = results[agent]
        n = len(records)
        if n == 0:
            print(f"{agent:<20}{0:>4}")
            continue
        index = _series(records, "avg_total_dof_index")
        if not any(index):
            index = _series(records, "avg_dof")
        irr = _series(records, "irreversibility_ratio")
        issued = _series(records, "actions_issued")
        skipped = _series(records, "skipped_turns")

        lo, hi = ci95(index)
        index_by_agent[agent] = index
        print(f"{agent:<20}{n:>4}{mean(index):>10.3f}"
              f"{f'[{lo:.3f}, {hi:.3f}]':>22}"
              f"{mean(irr):>9.3f}"
              f"{mean(issued):>8.1f}{mean(skipped):>9.1f}")

    # Pairwise comparison against the random baseline.
    baseline = index_by_agent.get("random")
    if baseline and len(baseline) > 1:
        print("\n" + "=" * 96)
        print("DIFFERENCE vs random baseline (DOF-SPEC index) — bootstrap 95% CI, "
              ">0 favours the agent")
        print("=" * 96)
        print(f"{'Agent':<20}{'Δ mean':>10}{'95% CI':>22}{'Cohen d':>10}{'Verdict':>18}")
        print("-" * 96)
        for agent in agents:
            if agent == "random" or agent not in index_by_agent:
                continue
            values = index_by_agent[agent]
            if len(values) < 2:
                print(f"{agent:<20}{mean(values) - mean(baseline):>10.3f}"
                      f"{'n/a (need N>=2)':>22}")
                continue
            lo, hi, point = bootstrap_diff_ci(values, baseline)
            d = cohens_d(values, baseline)
            if lo > 0:
                verdict = "better"
            elif hi < 0:
                verdict = "worse"
            else:
                verdict = "n.s."
            print(f"{agent:<20}{point:>10.3f}{f'[{lo:.3f}, {hi:.3f}]':>22}"
                  f"{d:>10.2f}{verdict:>18}")

    # Plot: AvgDoF per episode with mean ± 95% CI.
    if index_by_agent:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
        names = list(index_by_agent)
        positions = range(len(names))
        means = [mean(index_by_agent[n]) for n in names]
        lows, highs = zip(*(ci95(index_by_agent[n]) for n in names))
        err = [
            [m - lo for m, lo in zip(means, lows)],
            [hi - m for m, hi in zip(means, highs)],
        ]
        ax1.bar(positions, means, yerr=err, capsize=5, color="#4c72b0", alpha=0.85)
        ax1.set_xticks(list(positions))
        ax1.set_xticklabels(names, rotation=30, ha="right")
        ax1.set_ylabel("DOF-SPEC index Σ ln(DoF) (mean, 95% CI)")
        ax1.set_title("Mean DOF-SPEC index per agent")

        for agent in names:
            series = index_by_agent[agent]
            ax2.plot(range(1, len(series) + 1), series, marker="o", ms=3, label=agent)
        ax2.set_xlabel("episode")
        ax2.set_ylabel("DOF-SPEC index")
        ax2.set_title("Per-episode DOF-SPEC index")
        ax2.legend(fontsize=8)
        ax2.grid(alpha=0.3)

        fig.tight_layout()
        fig.savefig(DEFAULT_PLOT, dpi=130)
        print(f"\nSaved plot to {DEFAULT_PLOT}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())