#!/usr/bin/env bash
# §10.36: проверка V3-1. Ожидания объявлены заранее (см. документ).
# 6 игр × 30 ходов, срез индекса на каждом ходу + действия за ход.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/v31.json /tmp/v31.json.state.jsonl
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 6 --turns 30 --aifill 6 --only dof_defensive \
  --dump-state 30 --output /tmp/v31.json > /tmp/v31.log 2>&1
echo "rc=$?  срезов индекса: $(grep -c 'индекс DoF' /tmp/v31.log 2>/dev/null || echo 0)"
echo готово