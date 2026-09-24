#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> DOF-MODEL-CIV setup"

# If python is not available, use nix-shell
if ! command -v python &>/dev/null; then
    echo "==> Using nix-shell for Python..."
    exec nix-shell -p python312 python312.pkgs.pip python312.pkgs.virtualenv cargo rustc maturin pkg-config openssl libffi libxcrypt --run "bash scripts/setup.sh"
fi

# --- 1. Create venv fresh ---
echo "==> Creating venv..."
rm -rf .venv
python -m venv .venv --system-site-packages

source .venv/bin/activate

# --- 2. Install dependencies (with --break-system-packages for NixOS) ---
echo "==> Installing dependencies..."
pip install --break-system-packages --upgrade pip
pip install --break-system-packages pydantic numpy pandas matplotlib pytest ray 2>/dev/null || true

# --- 3. Install project ---
echo "==> Installing project..."
pip install --break-system-packages -e .

# --- 4. Build Rust core if needed ---
if ! python -c "import dof_core" 2>/dev/null; then
    echo "==> Building Rust core..."
    cd brain/core
    export PYO3_PYTHON="$(which python)"
    nix-shell -p cargo rustc maturin --run "maturin build --release --out dist"
    cd ../..
    
    echo "==> Installing Rust wheel..."
    WHEEL=$(ls brain/core/dist/dof_core-*.whl 2>/dev/null | head -1)
    if [ -n "$WHEEL" ]; then
        pip install --break-system-packages --force-reinstall --no-deps "$WHEEL"
    fi
fi

# --- 5. Verify ---
echo "==> Verifying..."
python -c "
import env, dof_core, pydantic, numpy, pytest
print('✅ All dependencies ready')
"

echo ""
echo "==> Done! Run: pytest tests/"
