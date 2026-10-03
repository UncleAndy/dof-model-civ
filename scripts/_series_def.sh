#!/usr/bin/env bash
# §10.113/§10.114: проверка прикрытия города и отпора. 8 партий, сиды 9230–9237, 150 ходов.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
cp knowledge/world.json knowledge/world_def.json
V2_STORE="$P/knowledge/world_def.json" \
V2_TRACE="$P/knowledge/traces_def.jsonl" \
V2_RESULTS="$P/knowledge/results_def.jsonl" \
V2_DEFENSE="$P/knowledge/city_defense_def.jsonl" \
V2_INCURSION="$P/knowledge/city_incursion_def.jsonl" \
V2_TURNS=150 V2_SEEDS=9230,9231,9232,9233,9234,9235,9236,9237 V2_PORT_BASE=6321 \
"$P/.venv/bin/python" scripts/v2_play.py
echo "===== ГОТОВО ====="