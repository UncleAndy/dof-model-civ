#!/usr/bin/env bash
# DOF-MODEL-CIV — environment setup.
#
# Creates a python3.12 venv with --system-site-packages (so nixpkgs-provided
# numpy / pydantic / matplotlib are visible), then installs gymnasium, the
# vendored civrealm clone and this project in editable mode.
#
# Prefer `bash do.sh setup`, which calls the same logic.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

VENV=".venv"
PY="$VENV/bin/python"

echo "==> Recreating $VENV..."
rm -rf "$VENV"
python3.12 -m venv "$VENV" --system-site-packages

echo "==> Installing dependencies..."
"$PY" -m pip install --upgrade pip
"$PY" -m pip install numpy gymnasium pydantic matplotlib
"$PY" -m pip install -e .

if [ -d civrealm ]; then
    echo "==> Installing vendored civrealm (editable)..."
    (cd civrealm && "$ROOT/$VENV/bin/python" -m pip install -e .)
fi

echo "==> Verifying imports..."
"$PY" -c "import numpy, gymnasium, civrealm; print('OK')"

echo "==> Setup complete."