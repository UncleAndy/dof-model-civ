#!/usr/bin/env bash
# §10.44: добираем число игр. Три ветви × 12 игр × 150 ходов, правило вердикта объявлено заранее.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore

run() {   # run <метка> <флаги...>
  local tag="$1"; shift
  rm -f "/tmp/h150n12_${tag}.json" "/tmp/h150n12_${tag}.json.state.jsonl"
  echo "=== ${tag}: 12 игр × 150 ходов ==="
  .venv/bin/python baselines/run_real_tournament.py \
    --episodes 12 --turns 150 --aifill 6 --only dof_defensive \
    --dump-state 150 --output "/tmp/h150n12_${tag}.json" "$@" \
    > "/tmp/h150n12_${tag}.log" 2>&1
  echo "${tag}: rc=$?  строк срезов $(wc -l < "/tmp/h150n12_${tag}.json.state.jsonl" 2>/dev/null || echo 0)"
}

run base
run ban --ban-produce Warriors
run legacy --no-forecast
echo готово