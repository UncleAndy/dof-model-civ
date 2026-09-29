#!/usr/bin/env bash
# §10.59: ветвь ПРЕЖНИЙ ПУТЬ/ВЫКЛ на объявленной оси империи.
# Те же 12 карт, что у серии c300 (mapseed 9000+i), 300 ходов, прибор состава счёта.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore

PREFIX="${PREFIX:-leg300}"
SEED="${SEED_BASE:-9000}"

rm -f "/tmp/${PREFIX}_legacy.json" "/tmp/${PREFIX}_legacy.json.state.jsonl"
echo "=== legacy (ВЫКЛ): 12 карт × 300 ходов (mapseed ${SEED}+i), мера — ось империи ==="
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 12 --turns 300 --aifill 6 --only dof_defensive --seed-base "$SEED" \
  --timeout 1500 --dump-state 300 --no-forecast \
  --output "/tmp/${PREFIX}_legacy.json" > "/tmp/${PREFIX}_legacy.log" 2>&1
echo "legacy: rc=$?  строк срезов $(wc -l < "/tmp/${PREFIX}_legacy.json.state.jsonl" 2>/dev/null || echo 0)"
echo "готово ВЫКЛ на оси империи (${PREFIX}, карты от ${SEED})"