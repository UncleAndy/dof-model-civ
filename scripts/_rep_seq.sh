#!/usr/bin/env bash
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore

run () {
  local n=$1 port=$2
  cp knowledge/world.json knowledge/world_seq$n.json
  V2_STORE="$P/knowledge/world_seq$n.json" \
  V2_TRACE="$P/knowledge/traces_seq$n.jsonl" \
  V2_TURNS=150 V2_SEEDS=9230 V2_PORT_BASE=$port \
  V2_GROWTH="$P/knowledge/city_growth_seq$n.jsonl" \
  V2_DEFENSE="$P/knowledge/city_defense_seq$n.jsonl" \
  "$P/.venv/bin/python" scripts/v2_play.py
}

echo "===== ПОСЛЕДОВАТЕЛЬНЫЙ ПРОГОН 1 (порт 6329) ====="
run 1 6329
echo "===== ПОСЛЕДОВАТЕЛЬНЫЙ ПРОГОН 2 (порт 6330) ====="
run 2 6330
echo "===== ГОТОВО ====="
