#!/usr/bin/env bash
# Серия §10.29: механизм ранней потери города. Две ветви, один и тот же мир.
# Ветви различаются ТОЛЬКО прогнозом: --no-forecast против прогноза.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/death_off.json /tmp/death_off.json.state.jsonl
rm -f /tmp/death_on.json  /tmp/death_on.json.state.jsonl

echo "=== ВЫКЛ (прежний путь), 8 игр x 25 ходов, 6 игроков ==="
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 8 --turns 25 --aifill 6 --only dof_defensive --no-forecast \
  --dump-state 25 --output /tmp/death_off.json > /tmp/death_off.log 2>&1
echo "ВЫКЛ rc=$?  игр со срезами: $(wc -l < /tmp/death_off.json.state.jsonl 2>/dev/null || echo 0)"

echo "=== ПРОГНОЗ, 8 игр x 25 ходов, 6 игроков ==="
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 8 --turns 25 --aifill 6 --only dof_defensive \
  --dump-state 25 --output /tmp/death_on.json > /tmp/death_on.log 2>&1
echo "ПРОГНОЗ rc=$?  игр со срезами: $(wc -l < /tmp/death_on.json.state.jsonl 2>/dev/null || echo 0)"
echo "готово"