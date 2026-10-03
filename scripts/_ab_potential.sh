#!/usr/bin/env bash
# §10.112: проверка эффекта «потенциальный источник» (§10.111). Протокол объявлен ДО данных.
# Арм A (OFF, V2_NO_POTENTIAL=1) и арм B (ON), одни сиды 9230–9237, 150 ходов.
# Вердикт §10.95: медиана B−A ≥ 2 очка И ≥10% медианы A И знаковый p<0.05.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
SEEDS="9230,9231,9232,9233,9234,9235,9236,9237"

echo "===== АРМ A (механизм ВЫКЛЮЧЕН) ====="
cp knowledge/world.json knowledge/world_abA.json
V2_NO_POTENTIAL=1 \
V2_STORE="$P/knowledge/world_abA.json" V2_TRACE="$P/knowledge/traces_abA.jsonl" \
V2_RESULTS="$P/knowledge/results_abA.jsonl" V2_TURNS=150 V2_SEEDS="$SEEDS" V2_PORT_BASE=6300 \
"$P/.venv/bin/python" scripts/v2_play.py

echo "===== АРМ B (механизм ВКЛЮЧЕН) ====="
cp knowledge/world.json knowledge/world_abB.json
V2_STORE="$P/knowledge/world_abB.json" V2_TRACE="$P/knowledge/traces_abB.jsonl" \
V2_RESULTS="$P/knowledge/results_abB.jsonl" V2_TURNS=150 V2_SEEDS="$SEEDS" V2_PORT_BASE=6308 \
"$P/.venv/bin/python" scripts/v2_play.py

echo "===== ГОТОВО ====="