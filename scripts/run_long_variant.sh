#!/usr/bin/env bash
# Chained experiment: wait for the 30-turn tournament to finish and be analysed,
# then run the long-game variant with a deeper prediction horizon, then analyse
# that too. Everything is logged under logs/.
#
# Usage: scripts/run_long_variant.sh <pid_of_running_tournament>
#
# Rationale for the settings:
#   * 30 -> 150 turns: the game's own scoring is sparse (every 150 turns) and the
#     entity set does not change within 30 turns, so a longer horizon is needed
#     before any growth in the index is even possible.
#   * lookahead 3 -> 5: DOF-Core's prediction depth. Measured cost on a 95-entity
#     state (candidates ** horizon): (3,3) 0.2 ms, (5,5) 15 ms, (8,5) ~0.2 s per
#     decision — affordable, so the horizon can be deepened without shrinking the
#     shortlist.
set -u -o pipefail

PID="${1:?usage: run_long_variant.sh <pid_of_running_tournament>}"
P="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$P/.venv/bin/python"
LOGS="$P/logs"
mkdir -p "$LOGS"

NIX_SP="$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')"
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$NIX_SP"
export PYTHONWARNINGS=ignore

say() { echo "[$(date -u +%H:%M:%S)] $*"; }

# ── 1. wait for the running tournament ────────────────────────────────────────
say "waiting for tournament pid=$PID to finish"
while kill -0 "$PID" 2>/dev/null; do sleep 30; done
say "tournament pid=$PID finished; settling 20s"
sleep 20

# ── 2. analyse the 30-turn dataset ───────────────────────────────────────────
cp -f "$P/tournament_results.json" "$P/tournament_results_30t.json"
say "analysing tournament_results_30t.json (turns=30, lookahead=3)"
"$PY" "$P/baselines/analyze.py" "$P/tournament_results_30t.json" \
    > "$LOGS/analyze_30t.log" 2>&1
say "analysis of 30-turn run done -> logs/analyze_30t.log"

# ── 3. long-game variant ─────────────────────────────────────────────────────
say "starting LONG variant: turns=150 lookahead=5 max_candidates=8 (14 matches)"
"$PY" "$P/baselines/run_real_tournament.py" \
    --episodes 2 --turns 150 --timeout 900 --retries 2 --port-wait 180 \
    --lookahead 5 --max-candidates 8 \
    --output "$P/tournament_results_long.json" \
    > "$LOGS/long_tournament.log" 2>&1
say "long variant finished (exit=$?)"

# ── 4. analyse the long dataset ──────────────────────────────────────────────
if [ -f "$P/tournament_results_long.json" ]; then
    "$PY" "$P/baselines/analyze.py" "$P/tournament_results_long.json" \
        > "$LOGS/analyze_long.log" 2>&1
    say "analysis of long run done -> logs/analyze_long.log"
fi

say "chain complete"
echo "=== analyze_30t.log ==="
cat "$LOGS/analyze_30t.log"
echo "=== analyze_long.log ==="
cat "$LOGS/analyze_long.log"
echo "=== long_tournament.log (tail) ==="
tail -n 20 "$LOGS/long_tournament.log"