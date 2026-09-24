#!/usr/bin/env bash
set -euo pipefail

# DOF-MODEL-CIV — one-shot setup script.
# Run this from the project root after entering nix develop:
#
#   cd /home/hermes/projects/AI/DOF-MODEL-CIV
#   nix develop --impure
#   bash scripts/setup.sh
#
# Or run directly (nix-shell will be used automatically):
#
#   bash scripts/setup.sh

cd "$(dirname "$0")/.."

# If we're not in a nix shell with python, enter one
if ! command -v python &>/dev/null && command -v nix-shell &>/dev/null; then
    echo "==> Entering nix-shell..."
    exec nix-shell -p python312 python312.pkgs.pip python312.pkgs.virtualenv cargo rustc maturin pkg-config openssl libffi libxcrypt --run "bash scripts/setup.sh"
fi

echo "==> DOF-MODEL-CIV setup"

# --- 1. Create venv with correct ownership ---
VENV_DIR=".venv"
if [ ! -f "$VENV_DIR/bin/python" ] || [ ! -w "$VENV_DIR" ]; then
    echo "==> Creating venv..."
    rm -rf "$VENV_DIR"
    python -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# --- 2. Install Python dependencies ---
echo "==> Installing Python packages..."
pip install --upgrade pip
pip install pydantic numpy pandas matplotlib pytest ray 2>/dev/null || pip install pydantic numpy pytest ray

# --- 3. Install project in editable mode ---
echo "==> Installing dof-model-civ..."
pip install -e .

# --- 4. Install Rust core wheel if available ---
WHEEL="brain/core/dist/dof_core-0.1.0-cp312-cp312-linux_x86_64.whl"
if [ -f "$WHEEL" ]; then
    echo "==> Installing Rust core wheel..."
    pip install --force-reinstall --no-deps "$WHEEL" 2>/dev/null || echo "⚠️  Failed to install wheel (may need rebuild)"
else
    echo "==> ⚠️  Rust core wheel not found at $WHEEL"
    echo "    Build with: cd brain/core && nix-shell -p cargo rustc python3 maturin --run 'PYO3_PYTHON=\$(which python) maturin build --release'"
fi

# --- 5. Verify ---
echo "==> Verifying..."
python -c "
import sys
mods = ['env', 'dof_core', 'pydantic', 'numpy', 'pytest']
missing = []
for m in mods:
    try:
        __import__(m)
    except ImportError:
        missing.append(m)
if missing:
    print(f'❌ Missing: {missing}', file=sys.stderr)
    sys.exit(1)
else:
    print('✅ All dependencies ready!')
"

echo ""
echo "==> Setup complete!"
echo ""
echo "Quick reference:"
echo "  pytest tests/                     — run all tests"
echo "  pytest tests/unit/test_core.py -v — test Rust core"
echo "  python scripts/capture_obs.py     — capture game data"
