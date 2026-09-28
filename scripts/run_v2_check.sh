#!/usr/bin/env bash
# §10.38: проверка V2 (шаг несёт долю R/N). Ожидания объявлены заранее.
# 6 игр × 30 ходов; срезы кандидатов (видно прогресс) и состояния (видно действия).
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/v2.json /tmp/v2.json.state.jsonl
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 6 --turns 30 --aifill 6 --only dof_defensive \
  --dump-candidates 30 --dump-state 30 --output /tmp/v2.json > /tmp/v2.log 2>&1
echo "rc=$?  срезов кандидатов: $(grep -c '\[кандидаты\]' /tmp/v2.log 2>/dev/null || echo 0)"
echo готово