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
            python312.pkgs.matplotlib
            python312.pkgs.pytest
            pkgs.cargo
            pkgs.rustc
            pkgs.maturin
            pkgs.pkg-config
            pkgs.openssl
          ];

          shellHook = ''
            echo "==> DOF-MODEL-CIV"

            # Use venv Python if it exists
            if [ -f ".venv/bin/python" ]; then
              export VIRTUAL_ENV="$(pwd)/.venv"
              export PATH="$VIRTUAL_ENV/bin:$PATH"
              echo "==> Using venv: $VIRTUAL_ENV"
            else
              echo "==> No venv found. Run: bash do.sh setup"
            fi

            echo ""
            echo "Commands:"
            echo "  bash do.sh setup    — create venv, install deps, build Rust"
            echo "  pytest tests/      — run tests (use venv pytest)"
            echo "  bash do.sh match    — run a match"
            echo ""
          '';
        };
      });
}
