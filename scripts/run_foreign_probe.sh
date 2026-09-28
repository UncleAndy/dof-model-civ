#!/usr/bin/env bash
# §10.33: чужие сущности в общем DoF и признак «источник коллапса».
# 6 игр × 30 ходов, тесная посадка (6 игроков) — нужны ЧУЖИЕ юниты в наблюдении.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/foreign.json /tmp/foreign.json.state.jsonl
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 6 --turns 30 --aifill 6 --only dof_defensive \
  --dump-state 30 --output /tmp/foreign.json > /tmp/foreign.log 2>&1
echo "rc=$?  чужих срезов: $(grep -c 'чужое в DoF' /tmp/foreign.log 2>/dev/null || echo 0)"
echo готово