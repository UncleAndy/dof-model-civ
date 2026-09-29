#!/usr/bin/env bash
# §10.43, третий замер: ветвь, которая ДВИГАЕТСЯ и ОСНОВЫВАЕТ (прежний путь, ВЫКЛ).
# Вопрос: окупается ли расширение на 150 ходах? Дизайн тот же, что у БАЗЫ (4 × 150 × 6).
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/h150_legacy.json /tmp/h150_legacy.json.state.jsonl
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 4 --turns 150 --aifill 6 --only dof_defensive --no-forecast \
  --dump-state 150 --output /tmp/h150_legacy.json > /tmp/h150_legacy.log 2>&1
echo "legacy: rc=$?  строк срезов $(wc -l < /tmp/h150_legacy.json.state.jsonl 2>/dev/null || echo 0)"
echo готово