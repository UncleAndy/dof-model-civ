#!/usr/bin/env bash
# §10.47: серия на 300 ходах. Ставится в цепочку за кругом 2 (150 ходов),
# чтобы не запускать две серии на стенде одновременно.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore

R2_PID="${1:-}"
if [ -n "$R2_PID" ]; then
  echo "ждём окончания круга 2 (pid $R2_PID)…"
  while kill -0 "$R2_PID" 2>/dev/null; do sleep 30; done
  echo "круг 2 закончился, начинаем 300 ходов"
fi

run() {   # run <метка> <флаги...>
  local tag="$1"; shift
  rm -f "/tmp/h300_${tag}.json" "/tmp/h300_${tag}.json.state.jsonl"
  echo "=== ${tag}: 12 игр × 300 ходов ==="
  .venv/bin/python baselines/run_real_tournament.py \
    --episodes 12 --turns 300 --aifill 6 --only dof_defensive \
    --dump-state 300 --output "/tmp/h300_${tag}.json" "$@" \
    > "/tmp/h300_${tag}.log" 2>&1
  echo "${tag}: rc=$?  строк срезов $(wc -l < "/tmp/h300_${tag}.json.state.jsonl" 2>/dev/null || echo 0)"
}

run base
run ban --ban-produce Warriors
run legacy --no-forecast
echo "готово 300"