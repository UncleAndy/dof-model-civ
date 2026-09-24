#!/usr/bin/env bash
# DOF-MODEL-CIV — Test runner script
# Usage: bash scripts/test.sh

set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Running tests..."

# Check if venv exists
if [ ! -f ".venv/bin/python" ]; then
    echo "==> venv not found. Run: bash scripts/setup.sh"
    exit 1
fi

# Use venv's pytest
.venv/bin/python -m pytest tests/ -v "$@"
