#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Building Rust core (PyO3 + maturin)..."

# Ensure we're in a Nix dev shell or have maturin available
if ! command -v maturin &>/dev/null; then
    echo "maturin not found. Entering nix develop..."
    nix develop --impure --command bash "$0"
    exit 0
fi

cd brain/core

echo "==> Building with maturin..."
maturin develop --release --manifest-path Cargo.toml

echo "==> Build complete!"
echo "==> Testing Python import..."

cd ../..
.venv/bin/python -c "
from dof_core import DOFCalculusCore, CoreEntity, CoreAction
core = DOFCalculusCore(lookahead_horizon=3, context_switch_penalty=0.5)
print(f'Core created: horizon={core.lookahead_horizon}, csp={core.context_switch_penalty}')
print('✅ Rust core loaded successfully!')
"
