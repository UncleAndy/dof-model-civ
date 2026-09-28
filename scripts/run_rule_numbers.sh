#!/usr/bin/env bash
# §10.30: числа для защитного правила на большой выборке действий.
# Ветвь ВЫКЛ (она трогает граждан), 12 игр x 14 ходов, полный прибор (окно клеток).
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/rule_off.json /tmp/rule_off.json.state.jsonl
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 12 --turns 14 --aifill 6 --only dof_defensive --no-forecast \
  --dump-state 14 --output /tmp/rule_off.json > /tmp/rule_off.log 2>&1
echo "rc=$?  строк срезов: $(wc -l < /tmp/rule_off.json.state.jsonl 2>/dev/null || echo 0)"
echo готово