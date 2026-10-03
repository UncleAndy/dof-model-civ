#!/usr/bin/env bash
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
export V2_STORE=$P/knowledge/world_sm3.json
export V2_TRACE=$P/knowledge/traces_sm3.jsonl
export V2_DEFENSE=$P/knowledge/city_defense_sm3.jsonl
export V2_INCURSION=$P/knowledge/city_incursion_sm3.jsonl
export V2_TURNS=90
export V2_SEEDS=9240
export V2_PORT_BASE=6320
"$P/.venv/bin/python" scripts/v2_play.py > /tmp/sm3.log 2>&1
echo "SMOKE_DONE exit=$?"
tail -2 /tmp/sm3.log
