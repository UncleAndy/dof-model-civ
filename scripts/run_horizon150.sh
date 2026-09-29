#!/usr/bin/env bash
# §10.42: проверка горизонта. База против запрета производства, по 4 игры × 150 ходов.
# Ожидания объявлены ДО данных (см. документ §10.42).
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore

run() {   # run <метка> <флаги...>
  local tag="$1"; shift
  rm -f "/tmp/h150_${tag}.json" "/tmp/h150_${tag}.json.state.jsonl"
  .venv/bin/python baselines/run_real_tournament.py \
    --episodes 4 --turns 150 --aifill 6 --only dof_defensive \
    --dump-state 150 --output "/tmp/h150_${tag}.json" "$@" \
    > "/tmp/h150_${tag}.log" 2>&1
  echo "${tag}: rc=$?  строк срезов $(wc -l < "/tmp/h150_${tag}.json.state.jsonl" 2>/dev/null || echo 0)"
}

echo "=== БАЗА: 4 игры × 150 ходов ==="
run base
echo "=== ЗАПРЕТ Warriors: 4 игры × 150 ходов ==="
run ban --ban-produce Warriors
echo готово