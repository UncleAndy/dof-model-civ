#!/usr/bin/env bash
# §10.40: вредна ли «беговая дорожка»? Запрет постановки Warriors в очередь.
# Дизайн совпадает с серией проверки V2 (6 игр × 30 ходов × 6 игроков), чтобы
# сравнивать напрямую: счёт 32.0, смертей 0, основано 6 городов, движения 0.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/ban.json /tmp/ban.json.state.jsonl
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 6 --turns 30 --aifill 6 --only dof_defensive \
  --ban-produce Warriors --dump-state 30 --output /tmp/ban.json > /tmp/ban.log 2>&1
echo "rc=$?  срезов: $(wc -l < /tmp/ban.json.state.jsonl 2>/dev/null || echo 0)"
echo готово