{
  description = "DOF-MODEL-CIV — Virtual sandbox for testing DOF-Core on 4X strategy";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        python312 = pkgs.python312;
      in
      {
        devShells.default = pkgs.mkShell {
          name = "dof-model-civ";

          buildInputs = [
            python312
            python312.pkgs.pip
            python312.pkgs.virtualenv
            python312.pkgs.pydantic
            python312.pkgs.numpy
            python312.pkgs.pandas
            python312.pkgs.matplotlib
            python312.pkgs.pytest
            pkgs.cargo
            pkgs.rustc
            pkgs.maturin
            pkgs.pkg-config
            pkgs.openssl
            pkgs.libffi
            pkgs.libxcrypt
          ];

          shellHook = ''
            set -uo pipefail

            echo "==> DOF-MODEL-CIV"

            # --- 1. Create venv fresh (handles ownership) ---
            if [ -d ".venv" ]; then
              if [ ! -w ".venv" ]; then
                echo "==> Removing old venv (wrong owner)..."
                rm -rf .venv
              fi
            fi

            if [ ! -f ".venv/bin/python" ]; then
              echo "==> Creating venv..."
              python -m venv .venv --system-site-packages
            fi

            source .venv/bin/activate

            # --- 2. Install project if needed ---
            if ! python -c "import env" 2>/dev/null; then
              echo "==> Installing project..."
              pip install --break-system-packages --quiet -e . 2>/dev/null || true
            fi

            # --- 3. Install Rust core wheel ---
            if ! python -c "import dof_core" 2>/dev/null; then
              echo "==> Installing Rust core..."
              pip install --break-system-packages --quiet --force-reinstall --no-deps \
                brain/core/dist/dof_core-0.1.0-cp312-cp312-linux_x86_64.whl 2>/dev/null || true
            fi

            # --- 4. Verify ---
            python -c "
            import sys
            mods = ['env', 'dof_core', 'pydantic', 'numpy', 'pytest']
            missing = [m for m in mods if not __import__(m, fromlist=['_'])]
            if missing:
              print(f'⚠️  Missing: {missing}')
              sys.exit(1)
            else:
              print('✅ All ready')
            "
          '';
        };
      });
}
