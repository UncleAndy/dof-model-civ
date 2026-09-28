#!/usr/bin/env bash
# §10.30: измерить арифметику еды на ЖИВЫХ данных.
# Ветвь ВЫКЛ (она трогает граждан), 3 игры x 10 ходов: нужно много наблюдений
# города и действий по клеткам, но мало времени.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/food_arith.json /tmp/food_arith.json.state.jsonl
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 3 --turns 10 --aifill 6 --only dof_defensive --no-forecast --trace \
  --dump-state 10 --output /tmp/food_arith.json > /tmp/food_arith.log 2>&1
echo "rc=$?  строк срезов: $(wc -l < /tmp/food_arith.json.state.jsonl 2>/dev/null || echo 0)"
echo готово