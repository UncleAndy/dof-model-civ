#!/usr/bin/env bash
# DOF-MODEL-CIV — Development helper
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"

setup() {
    echo "==> Setting up DOF-MODEL-CIV..."
    if [ ! -f "$VENV/bin/python" ]; then
        python -m venv "$VENV"
    fi
    "$VENV/bin/python" -m pip install --break-system-packages --upgrade pip
    "$VENV/bin/python" -m pip install --break-system-packages pydantic numpy matplotlib pytest gymnasium ray
    "$VENV/bin/python" -m pip install --break-system-packages -e . 2>/dev/null || true
    "$VENV/bin/python" -m pip install --break-system-packages -e civrealm 2>/dev/null || true

    if ! "$VENV/bin/python" -c "import dof_core" 2>/dev/null; then
        cd brain/core
        export PYO3_PYTHON="$("$VENV/bin/python" -c 'import sys; print(sys.executable)')"
        [ -d dist ] && rm -rf dist
        maturin build --release --out dist
        cd ../..
        "$VENV/bin/python" -m pip install --break-system-packages --force-reinstall --no-deps brain/core/dist/dof_core-*.whl
    fi
    echo "==> Setup complete! Run: bash do.sh test"
}

run_tests() {
    [ ! -f "$VENV/bin/python" ] && { echo "==> No venv. Run: bash do.sh setup"; exit 1; }
    "$VENV/bin/python" -m pytest tests/ -v "$@"
}

run_tournament() {
    [ ! -f "$VENV/bin/python" ] && { echo "==> No venv. Run: bash do.sh setup"; exit 1; }
    "$VENV/bin/python" baselines/run_tournament.py "$@"
}

run_real_tournament() {
    [ ! -f "$VENV/bin/python" ] && { echo "==> No venv. Run: bash do.sh setup"; exit 1; }
    "$VENV/bin/python" baselines/run_real_tournament.py "$@"
}

run_analyze() {
    [ ! -f "$VENV/bin/python" ] && { echo "==> No venv. Run: bash do.sh setup"; exit 1; }
    "$VENV/bin/python" baselines/analyze.py tournament_results.json 2>/dev/null || echo "==> No results file. Run: bash do.sh tournament"
}

run_match() {
    [ ! -f "$VENV/bin/python" ] && { echo "==> No venv. Run: bash do.sh setup"; exit 1; }
    "$VENV/bin/python" baselines/random_agent.py "$@"
}

run_no_op() {
    [ ! -f "$VENV/bin/python" ] && { echo "==> No venv. Run: bash do.sh setup"; exit 1; }
    "$VENV/bin/python" baselines/no_op_agent.py "$@"
}

run_dof_match() {
    [ ! -f "$VENV/bin/python" ] && { echo "==> No venv. Run: bash do.sh setup"; exit 1; }
    "$VENV/bin/python" baselines/dof_agent.py "$@"
}

do_clean() {
    echo "==> Cleaning..."
    rm -rf "$VENV" brain/core/dist
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    echo "==> Cleaned!"
}

case "${1:-help}" in
    setup)          setup ;;
    test)           shift; run_tests "$@" ;;
    match)          shift; run_match "$@" ;;
    no-op)          shift; run_no_op "$@" ;;
    dof-match)      shift; run_dof_match "$@" ;;
    tournament)     shift; run_tournament "$@" ;;
    real-tournament) shift; run_real_tournament "$@" ;;
    analyze)        shift; run_analyze "$@" ;;
    clean)          do_clean ;;
    help|--help|-h)
        echo "DOF-MODEL-CIV"
        echo ""
        echo "Usage: bash do.sh <command>"
        echo ""
        echo "Commands:"
        echo "  setup            Create venv, install deps, build Rust core"
        echo "  test             Run all tests"
        echo "  match            Run random baseline"
        echo "  no-op            Run no-op baseline"
        echo "  dof-match        Run DOF agent"
        echo "  tournament       Run synthetic tournament"
        echo "  real-tournament  Run real CivRealm tournament (needs Docker)"
        echo "  analyze          Analyze tournament results"
        echo "  clean            Remove venv and artifacts"
        ;;
    *)
        echo "Unknown: $1"
        exit 1
        ;;
esac
