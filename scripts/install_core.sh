#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Installing dof_core.so into venv..."

SO_SRC="brain/core/target/release/libdof_core.so"
SO_DST=".venv/lib/python3.12/site-packages/dof_core.so"

if [ ! -f "$SO_SRC" ]; then
    echo "ERROR: $SO_SRC not found. Run: cd brain/core && cargo build --release"
    exit 1
fi

# Remove old .so if exists
rm -f "$SO_DST"

# Copy new .so
cp "$SO_SRC" "$SO_DST"

echo "==> Installed $SO_DST"
echo "==> Testing Python import..."

.venv/bin/python -c "
import ctypes
import os
so_path = '.venv/lib/python3.12/site-packages/dof_core.so'
lib = ctypes.CDLL(so_path)
print(f'Loaded: {so_path}')
print(f'Symbols: {dir(lib)}')
print('✅ Rust core loaded successfully!')
"
