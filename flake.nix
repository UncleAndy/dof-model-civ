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
            pkgs.cargo
            pkgs.rustc
            pkgs.maturin
            pkgs.pkg-config
            pkgs.openssl
            pkgs.libffi
            pkgs.libxcrypt
          ];

          WHEEL_FILE = "brain/core/dist/dof_core-0.1.0-cp312-cp312-linux_x86_64.whl";

          shellHook = ''
            set -uo pipefail

            echo "==> DOF-MODEL-CIV"

            # --- 1. Fix venv ownership and permissions ---
            if [ -d ".venv" ]; then
              if [ ! -w ".venv" ]; then
                echo "==> Fixing venv permissions..."
                chmod -R u+w .venv
              fi
            fi

            # --- 2. Create venv if needed ---
            if [ ! -f ".venv/bin/python" ]; then
              echo "==> Creating venv..."
              rm -rf .venv
              python -m venv .venv
            fi

            source .venv/bin/activate

            # --- 3. Install dependencies if needed ---
            if ! python -c "import pydantic, numpy, pytest, ray, env, dof_core" 2>/dev/null; then
              echo "==> Installing dependencies..."
              pip install --quiet --upgrade pip
              pip install --quiet pydantic numpy matplotlib pytest ray 2>/dev/null || true
              pip install --quiet -e . 2>/dev/null || true

              if [ -f "$WHEEL_FILE" ]; then
                pip install --quiet --force-reinstall --no-deps "$WHEEL_FILE" 2>/dev/null || true
              fi
            fi

            # --- 4. Verify ---
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
              print(f'⚠️  Missing: {missing}')
              sys.exit(1)
            else:
              print('✅ All ready')
            "
          '';
        };
      });
}
