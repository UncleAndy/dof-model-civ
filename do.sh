#!/usr/bin/env bash
# DOF-MODEL-CIV — unified development helper.
#
# Usage: bash do.sh <command> [args...]
#
# Commands:
#   setup            create .venv, install deps, install project (editable)
#   test [pytest…]   run the test suite through the venv interpreter
#   match            run the random baseline against CivRealm
#   dof-match        run the DOF agent against CivRealm
#   real-tournament  run the real CivRealm tournament (all agents)
#   tournament       run the offline synthetic tournament
#   analyze          plot/analyse the last tournament results
#   clean            remove .venv and build artefacts
#   help             show this message
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
PY="$VENV/bin/python"

die_no_venv() {
    echo "==> No venv found. Run: bash do.sh setup"
    exit 1
}

setup() {
    echo "==> Setting up DOF-MODEL-CIV..."
    ROOT="$PWD"
    if [ ! -x "$PY" ]; then
        python3.12 -m venv "$VENV" --system-site-packages
    fi
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install numpy gymnasium pydantic matplotlib
    "$PY" -m pip install -e .
    if [ -d civrealm ]; then
        (cd civrealm && "$ROOT/$VENV/bin/python" -m pip install -e .)
    fi
    echo "==> Setup complete."
    echo "    py:      $PY"
    echo "    tests:   bash do.sh test"
    echo "    tourney: bash do.sh real-tournament --episodes 3 --turns 50 --port 6001"
}

run_tests() {
    [ -x "$PY" ] || die_no_venv
    "$PY" -m pytest tests/ -v "$@"
}

run_match() {
    [ -x "$PY" ] || die_no_venv
    "$PY" baselines/random_agent.py "$@"
}

run_dof_match() {
    [ -x "$PY" ] || die_no_venv
    "$PY" baselines/dof_agent.py "$@"
}

run_real_tournament() {
    [ -x "$PY" ] || die_no_venv
    "$PY" baselines/run_real_tournament.py "$@"
}

run_tournament() {
    [ -x "$PY" ] || die_no_venv
    "$PY" baselines/run_tournament.py "$@"
}

run_analyze() {
    [ -x "$PY" ] || die_no_venv
    "$PY" baselines/analyze.py "$@"
}

run_inspect_actions() {
    [ -x "$PY" ] || die_no_venv
    "$PY" scripts/inspect_actions.py "$@"
}

run_inspect_bridge() {
    [ -x "$PY" ] || die_no_venv
    "$PY" scripts/inspect_bridge.py "$@"
}

do_clean() {
    echo "==> Removing $VENV and caches..."
    rm -rf "$VENV" .pytest_cache
    find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    echo "==> Clean."
}

case "${1:-help}" in
    setup)            setup ;;
    test)             shift; run_tests "$@" ;;
    match)            shift; run_match "$@" ;;
    dof-match)        shift; run_dof_match "$@" ;;
    real-tournament)  shift; run_real_tournament "$@" ;;
    tournament)       shift; run_tournament "$@" ;;
    analyze)          shift; run_analyze "$@" ;;
    inspect-actions)  shift; run_inspect_actions "$@" ;;
    inspect-bridge)   shift; run_inspect_bridge "$@" ;;
    clean)            do_clean ;;
    help|--help|-h)
        echo "DOF-MODEL-CIV"
        echo ""
        echo "Usage: bash do.sh <command> [args...]"
        echo ""
        echo "  setup            create venv, install deps, install project"
        echo "  test [args]      run pytest via the venv"
        echo "  match            random baseline vs CivRealm"
        echo "  dof-match        DOF agent vs CivRealm"
        echo "  real-tournament  real CivRealm tournament (all agents)"
        echo "  tournament       offline synthetic tournament"
        echo "  analyze          analyse/plot tournament results"
        echo "  inspect-actions  dump the live action space (civrealm)"
        echo "  inspect-bridge   check which DOF candidates are executable"
        echo "  clean            remove venv and caches"
        ;;
    *)
        echo "Unknown command: $1"
        echo "Run: bash do.sh help"
        exit 1
        ;;
esac