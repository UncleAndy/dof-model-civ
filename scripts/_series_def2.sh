#!/usr/bin/env bash
# §10.113/§10.114: серия проверки (прикрытие города + отпор). 5 партий × 150 ходов.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
cp knowledge/world.json knowledge/world_def2.json
V2_STORE="$P/knowledge/world_def2.json" \
V2_TRACE="$P/knowledge/traces_def2.jsonl" \
V2_RESULTS="$P/knowledge/results_def2.jsonl" \
V2_DEFENSE="$P/knowledge/city_defense_def2.jsonl" \
V2_INCURSION="$P/knowledge/city_incursion_def2.jsonl" \
V2_TURNS=150 V2_SEEDS=9240,9241,9242,9243,9244 V2_PORT_BASE=6326 \
"$P/.venv/bin/python" scripts/v2_play.py
echo "===== ГОТОВО ====="