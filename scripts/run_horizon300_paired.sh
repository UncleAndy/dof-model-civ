#!/usr/bin/env bash
# §10.48/§10.49: СОПОСТАВЛЕННАЯ серия. 3 ветви × 12 карт (mapseed 9000+i — одни и те же во всех
# ветвях) × 300 ходов. Бюджет матча поднят до 1500 с (полная игра на 300 ходов ≈450 с).
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore

PREFIX="${PREFIX:-h300q}"
SEED="${SEED_BASE:-9000}"

run() {   # run <метка> <флаги...>
  local tag="$1"; shift
  rm -f "/tmp/${PREFIX}_${tag}.json" "/tmp/${PREFIX}_${tag}.json.state.jsonl"
  echo "=== ${tag}: 12 карт × 300 ходов (mapseed ${SEED}+i), бюджет 1500 с ==="
  .venv/bin/python baselines/run_real_tournament.py \
    --episodes 12 --turns 300 --aifill 6 --only dof_defensive --seed-base "$SEED" \
    --timeout 1500 \
    --dump-state 300 --output "/tmp/${PREFIX}_${tag}.json" "$@" \
    > "/tmp/${PREFIX}_${tag}.log" 2>&1
  echo "${tag}: rc=$?  строк срезов $(wc -l < "/tmp/${PREFIX}_${tag}.json.state.jsonl" 2>/dev/null || echo 0)"
}

run base
run ban --ban-produce Warriors
run legacy --no-forecast
echo "готово сопоставленная 300 (${PREFIX}, карты от ${SEED})"