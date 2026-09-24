#!/usr/bin/env bash
# DOF-MODEL-CIV — Development helper
# Usage: bash do.sh {setup|test|match|clean}

set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"

setup() {
    echo "==> Setting up DOF-MODEL-CIV..."

    # Create venv if needed
    if [ ! -f "$VENV/bin/python" ]; then
        echo "==> Creating venv..."
        python -m venv "$VENV"
    fi

    source "$VENV/bin/activate"

    # Install Python packages
    echo "==> Installing Python packages..."
    pip install --break-system-packages --upgrade pip
    pip install --break-system-packages pydantic numpy matplotlib pytest 2>/dev/null || true
    pip install --break-system-packages -e . 2>/dev/null || true

    # Build Rust core if needed
    if ! python -c "import dof_core" 2>/dev/null; then
        echo "==> Building Rust core..."
        cd brain/core
        export PYO3_PYTHON="$(which python)"
        [ -d dist ] && rm -rf dist
        maturin build --release --out dist
        cd ../..
        pip install --break-system-packages --force-reinstall --no-deps brain/core/dist/dof_core-*.whl
    fi

    echo ""
    echo "==> Setup complete!"
    echo "==> Activate: source $VENV/bin/activate"
    echo "==> Run tests: bash do.sh test"
}

run_tests() {
    if [ ! -f "$VENV/bin/python" ]; then
        echo "==> No venv found. Run: bash do.sh setup"
        exit 1
    fi
    source "$VENV/bin/activate"
    python -m pytest tests/ -v "$@"
}

run_match() {
    if [ ! -f "$VENV/bin/python" ]; then
        echo "==> No venv found. Run: bash do.sh setup"
        exit 1
    fi
    source "$VENV/bin/activate"
    python baselines/random_agent.py "$@"
}

run_dof_match() {
    if [ ! -f "$VENV/bin/python" ]; then
        echo "==> No venv found. Run: bash do.sh setup"
        exit 1
    fi
    source "$VENV/bin/activate"
    python baselines/dof_agent.py "$@"
}

run_tournament() {
    if [ ! -f "$VENV/bin/python" ]; then
        echo "==> No venv found. Run: bash do.sh setup"
        exit 1
    fi
    source "$VENV/bin/activate"
    python baselines/run_tournament.py "$@"
}

run_analyze() {
    if [ ! -f "$VENV/bin/python" ]; then
        echo "==> No venv found. Run: bash do.sh setup"
        exit 1
    fi
    source "$VENV/bin/activate"
    if [ -f "tournament_results.json" ]; then
        python baselines/analyze.py tournament_results.json
    else
        echo "==> No results file. Run: bash do.sh tournament"
    fi
}

do_clean() {
    echo "==> Cleaning..."
    rm -rf "$VENV"
    rm -rf brain/core/dist
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    echo "==> Cleaned!"
}

case "${1:-help}" in
    setup)      setup ;;
    test)       shift; run_tests "$@" ;;
    match)      shift; run_match "$@" ;;
    dof-match)  shift; run_dof_match "$@" ;;
    tournament) shift; run_tournament "$@" ;;
    analyze)    shift; run_analyze "$@" ;;
    clean)      do_clean ;;
    help|--help|-h)
        echo "DOF-MODEL-CIV"
        echo ""
        echo "Usage: bash do.sh <command>"
        echo ""
        echo "Commands:"
        echo "  setup      Create venv, install deps, build Rust core"
        echo "  test       Run all tests"
        echo "  match      Run random baseline"
        echo "  dof-match  Run DOF agent"
        echo "  tournament Run validation tournament"
        echo "  analyze    Analyze tournament results"
        echo "  clean      Remove venv and artifacts"
        ;;
    *)
        echo "Unknown: $1"
        exit 1
        ;;
esac
