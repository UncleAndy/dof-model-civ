#!/usr/bin/env bash
# §10.55: ПОДТВЕРЖДАЮЩАЯ серия на оси империи. БАЗА и ЗАПРЕТ × 12 карт (mapseed 10000+i) × 300 ходов.
# Мера исхода — ось империи (без юнитовых категорий и без площадей); правило вердикта — как §10.48.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore

PREFIX="${PREFIX:-emp300}"
SEED="${SEED_BASE:-10000}"

run() {   # run <метка> <флаги...>
  local tag="$1"; shift
  rm -f "/tmp/${PREFIX}_${tag}.json" "/tmp/${PREFIX}_${tag}.json.state.jsonl"
  echo "=== ${tag}: 12 карт × 300 ходов (mapseed ${SEED}+i), мера — ось империи ==="
  .venv/bin/python baselines/run_real_tournament.py \
    --episodes 12 --turns 300 --aifill 6 --only dof_defensive --seed-base "$SEED" \
    --timeout 1500 --dump-state 300 --output "/tmp/${PREFIX}_${tag}.json" "$@" \
    > "/tmp/${PREFIX}_${tag}.log" 2>&1
  echo "${tag}: rc=$?  строк срезов $(wc -l < "/tmp/${PREFIX}_${tag}.json.state.jsonl" 2>/dev/null || echo 0)"
}

run base
run ban --ban-produce Warriors
echo "готово подтверждение оси империи (${PREFIX}, карты от ${SEED})"