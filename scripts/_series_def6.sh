#!/usr/bin/env bash
# §10.113/§10.114 (исправлено): прикрытие города + отпор ТОЛЬКО по источнику коллапса.
# 8 партий × 150 ходов, те же сиды, что и def4 — для сравнения до/после правки.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
cp knowledge/world.json knowledge/world_def6.json
export V2_STORE=$P/knowledge/world_def6.json
export V2_TRACE=$P/knowledge/traces_def6.jsonl
export V2_DEFENSE=$P/knowledge/city_defense_def6.jsonl
export V2_INCURSION=$P/knowledge/city_incursion_def6.jsonl
export V2_GROWTH=$P/knowledge/city_growth_def6.jsonl
export V2_RESULTS=$P/knowledge/results_def6.jsonl
export V2_TURNS=150
export V2_SEEDS=9240,9241,9242,9243,9244,9245,9246,9247
export V2_PORT_BASE=6324
"$P/.venv/bin/python" scripts/v2_play.py > /tmp/def6.log 2>&1
echo "===== ГОТОВО exit=$? ====="
tail -3 /tmp/def6.log
