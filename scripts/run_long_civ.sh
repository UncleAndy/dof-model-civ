#!/usr/bin/env bash
# Long CivRealm tournament — run it when you are back at the machine:
#   bash scripts/run_long_civ.sh [episodes] [turns]
# Defaults: 100 episodes x 150 turns.
set -u -o pipefail
P="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$P/.venv/bin/python"
LOGS="$P/logs"
mkdir -p "$LOGS"
export PYTHONWARNINGS=ignore

EPISODES="${1:-100}"
TURNS="${2:-150}"
OUT="$P/tournament_results_long_civ.json"
LOG="$LOGS/long_civ_$(date -u +%Y%m%d_%H%M%S).log"

echo "==> CivRealm long: 7 agents x $EPISODES episodes x $TURNS turns"
echo "==> Output: $OUT"
echo "==> Log: $LOG"
echo "==> Time: $(date -u)"

"$PY" "$P/baselines/run_real_tournament.py" \
    --output "$OUT" \
    --episodes "$EPISODES" --turns "$TURNS" \
    --timeout 600 --settle 15 --retries 3 \
    --lookahead 3 --max-candidates 4 \
    --save-series \
    > "$LOG" 2>&1
rc=$?
echo "==> tournament exit=$rc at $(date -u)"

if [ -f "$OUT" ]; then
    "$PY" "$P/baselines/analyze.py" "$OUT" > "${OUT%.json}_analysis.log" 2>&1 || true
    echo "==> analysis saved to ${OUT%.json}_analysis.log"
fi
echo "==> last 15 lines of log:"
tail -15 "$LOG"
