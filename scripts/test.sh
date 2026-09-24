#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Activating venv..."
source .venv/bin/activate

echo "==> Installing dependencies..."
pip install -e ".[dev]" 2>/dev/null || pip install -e .

echo "==> Running tests..."
pytest tests/unit/test_entity_extractor.py -v "$@"
