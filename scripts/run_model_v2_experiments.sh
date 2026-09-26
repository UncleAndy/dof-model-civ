#!/usr/bin/env bash
# Autonomous experiment chain for the population-aware DoF model.
#
#  1. smoke:    does the new model let a DOF agent found cities at all?
#  2. measure:  re-measure per-action ΔDoF (founding must now be a GAIN)
#  3. 30-turn:  7 agents x 5 episodes x 30 turns      -> tournament_results_30t_v2.json
#  4. long:     7 agents x 2 episodes x 150 turns, lookahead 5, 8 candidates
#                                                     -> tournament_results_long.json
#  5. analyse every dataset (mean, 95% CI, bootstrap vs random)
#
# Everything lands in logs/. Slots: one match at a time, failed slots are
# blacklisted by the runner, and --settle gives Publite2 time to recycle.
set -u -o pipefail

P="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$P/.venv/bin/python"
LOGS="$P/logs"
mkdir -p "$LOGS"

NIX_SP="$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')"
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$NIX_SP"
export PYTHONWARNINGS=ignore

say() { echo "[$(date -u +%H:%M:%S)] $*"; }

tournament() {  # $1 = output json, rest = extra args
    local out="$1"; shift
    "$PY" "$P/baselines/run_real_tournament.py" --output "$out" "$@"
}

# ── 1. smoke ────────────────────────────────────────────────────────────────
say "smoke: dof_expansionist + random, 1 episode x 12 turns"
tournament "$P/tournament_results_smoke.json" \
    --only dof_expansionist,random --episodes 1 --turns 12 --timeout 300 \
    --settle 15 --retries 3 \
    > "$LOGS/smoke_v2.log" 2>&1
say "smoke done (exit=$?); tail:"
tail -n 8 "$LOGS/smoke_v2.log"

# ── 2. re-measure action deltas ─────────────────────────────────────────────
say "measuring per-action ΔDoF on the new model"
"$PY" "$P/scripts/measure_action_delta.py" --max-actions 14 \
    > "$LOGS/measure_deltas_v2.log" 2>&1
say "delta measurement done; founding lines:"
grep -E "build_city|found_city" "$LOGS/measure_deltas_v2.log" || echo "  (no founding action offered in that game)"

# ── 3. 30-turn tournament, new model ───────────────────────────────────────
say "30-turn tournament: 7 agents x 5 episodes x 30 turns (35 matches)"
tournament "$P/tournament_results_30t_v2.json" \
    --episodes 5 --turns 30 --timeout 300 --settle 10 --retries 3 \
    > "$LOGS/tournament_30t_v2.log" 2>&1
say "30-turn tournament done (exit=$?)"
"$PY" "$P/baselines/analyze.py" "$P/tournament_results_30t_v2.json" \
    > "$LOGS/analyze_30t_v2.log" 2>&1

# ── 4. long-game variant with deeper prediction ────────────────────────────
say "long variant: 7 agents x 2 episodes x 150 turns, lookahead 5, 8 candidates"
tournament "$P/tournament_results_long.json" \
    --episodes 2 --turns 150 --timeout 1200 --settle 15 --retries 3 \
    --lookahead 5 --max-candidates 8 \
    > "$LOGS/long_tournament.log" 2>&1
say "long variant done (exit=$?)"

if [ -f "$P/tournament_results_long.json" ]; then
    "$PY" "$P/baselines/analyze.py" "$P/tournament_results_long.json" \
        > "$LOGS/analyze_long.log" 2>&1
fi

say "chain complete"
echo "=== smoke_v2.log (tail) ===";        tail -n 12 "$LOGS/smoke_v2.log"
echo "=== measure_deltas_v2.log ===";      cat "$LOGS/measure_deltas_v2.log"
echo "=== analyze_30t_v2.log ===";         cat "$LOGS/analyze_30t_v2.log"
echo "=== analyze_long.log ===";           cat "$LOGS/analyze_long.log"