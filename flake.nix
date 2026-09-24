{
  description = "DOF-MODEL-CIV — Виртуальная песочница для проверки DOF-Core в 4X-стратегии";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, utils }:
    utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        pythonEnv = pkgs.python311;

        # Python-зависимости для разработки
        pythonPackages = pkgs.python311Packages;

        # Rust toolchain для сборки PyO3 core
        rustToolchain = pkgs.rustPlatform.rust.rustc.override {
          extensions = [ "rust-src" "rust-analyzer" ];
        };
      in
      {
        devShells.default = pkgs.mkShell {
          name = "dof-model-civ";

          buildInputs = [
            # Python
            pythonEnv
            pythonPackages.virtualenv
            pythonPackages.pip
            pythonPackages.setuptools
            pythonPackages.wheel
            pythonPackages.matplotlib
            pythonPackages.numpy
            pythonPackages.pandas
            pythonPackages.pydantic
            pythonPackages.pytest
            pythonPackages.ipython
            pythonPackages.jupyter
            pythonPackages.ruff

            # Rust (для brain/core PyO3)
            pkgs.rustc
            pkgs.cargo
            pkgs.maturin
            pkgs.rustfmt
            pkgs.clippy
            pkgs.rust-analyzer

            # Сборка
            pkgs.gcc
            pkgs.pkg-config
            pkgs.openssl
            pkgs.libffi

            # Docker (уже в системе, но для полноты)
            pkgs.docker
            pkgs.docker-compose

            # Утилиты
            pkgs.git
            pkgs.jq
            pkgs.just
            pkgs.sqlite
            pkgs.bun            # Для возможной интеграции с CivAgent (Node.js)
            pkgs.nodejs
          ];

          shellHook = ''
            echo "╔══════════════════════════════════════════════════════════╗"
            echo "║  DOF-MODEL-CIV — Dev Shell                              ║"
            echo "║  Python: $(python --version 2>&1)                       ║"
            echo "║  Rust:   $(rustc --version 2>&1)                        ║"
            echo "╚══════════════════════════════════════════════════════════╝"
            echo ""

            # Создаём virtualenv, если его нет
            if [ ! -d ".venv" ]; then
              echo "==> Создаю Python virtualenv..."
              virtualenv .venv
            fi
            source .venv/bin/activate

            # Устанавливаем Python-зависимости из pyproject.toml, если он есть
            if [ -f "pyproject.toml" ]; then
              echo "==> Устанавливаю Python-зависимости..."
              pip install -e ".[dev]" 2>/dev/null || pip install -e . 2>/dev/null || echo "==> [WARN] pyproject.toml не настроен, пропускаю pip install"
            fi

            # Проверяем CivRealm Docker
            if docker ps 2>/dev/null | grep -q freeciv-web; then
              echo "==> ✅ Freeciv-web Docker запущен"
            else
              echo "==> ⚠️  Freeciv-web Docker НЕ запущен"
              echo "      Запустите: bash scripts/setup.sh"
            fi

            echo ""
            echo "Доступные команды:"
            echo "  python - \"Python REPL\""
            echo "  pytest - \"Запуск тестов\""
            echo "  bash scripts/setup.sh - \"Запуск CivRealm Docker\""
            echo "  bash scripts/run_match.sh - \"Один матч\""
            echo ""
          '';
        };

        # Опционально: shell только для работы с Rust core
        devShells.rust = pkgs.mkShell {
          name = "dof-model-civ-rust";

          buildInputs = [
            pkgs.rustc
            pkgs.cargo
            pkgs.maturin
            pkgs.rustfmt
            pkgs.clippy
            pkgs.gcc
            pkgs.pkg-config
          ];

          shellHook = ''
            echo "Rust-only shell для brain/core разработки"
            cd brain/core 2>/dev/null || echo "[WARN] brain/core не найден"
          '';
        };

        # Опционально: shell только для Python-разработки (без Rust)
        devShells.python = pkgs.mkShell {
          name = "dof-model-civ-python";

          buildInputs = [
            pythonEnv
            pythonPackages.virtualenv
            pkgs.gcc
          ];

          shellHook = ''
            if [ ! -d ".venv" ]; then
              virtualenv .venv
            fi
            source .venv/bin/activate
            pip install -e ".[dev]" 2>/dev/null || echo "[WARN] pyproject.toml не настроен"
          '';
        };
      });
}
