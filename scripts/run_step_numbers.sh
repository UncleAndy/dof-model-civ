#!/usr/bin/env bash
# §10.34: числа по каждому шагу — решают, какой вариант фильтра имеет смысл.
# 3 игры × 5 ходов: нужны шаги ДО и ПОСЛЕ основания города.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/stepnums.json /tmp/stepnums.json.state.jsonl
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 3 --turns 5 --aifill 6 --only dof_defensive \
  --dump-candidates 5 --output /tmp/stepnums.json > /tmp/stepnums.log 2>&1
echo "rc=$?  срезов: $(grep -c '\[движение\]' /tmp/stepnums.log 2>/dev/null || echo 0)"
echo готово