#!/usr/bin/env bash
# DOF-MODEL-CIV — Run a single match
# Usage: bash scripts/match.sh [port]

set -euo pipefail

cd "$(dirname "$0")/.."

PORT=${1:-6001}

if [ ! -f ".venv/bin/python" ]; then
    echo "==> venv not found. Run: bash scripts/setup.sh"
    exit 1
fi

echo "==> Running match on port $PORT..."
.venv/bin/python -m baselines.random_agent --port "$PORT" "$@"
