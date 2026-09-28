#!/usr/bin/env bash
# §10.30: проверка Правила F по предрегистрации.
#   (а) ВЫКЛ + правило F   — ожидание: смертей 0/12, действий трёх семейств 0, surplus<0 = 0
#   (б) ВЫКЛ без правила    — КОНТРОЛЬ: должно воспроизвести смерти, как в записях
#   (в) прогноз + правило F — ожидание: прогноз не пострадал (смертей 0, решения есть)
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore

run() {   # run <метка> <доп.флаги...>
  local tag="$1"; shift
  rm -f "/tmp/fgate_${tag}.json" "/tmp/fgate_${tag}.json.state.jsonl"
  .venv/bin/python baselines/run_real_tournament.py \
    --episodes 12 --turns 14 --aifill 6 --only dof_defensive \
    --dump-state 14 --output "/tmp/fgate_${tag}.json" "$@" \
    > "/tmp/fgate_${tag}.log" 2>&1
  echo "${tag}: rc=$? строк срезов $(wc -l < "/tmp/fgate_${tag}.json.state.jsonl" 2>/dev/null || echo 0)  отсечено: $(grep -c 'правило F' "/tmp/fgate_${tag}.log" 2>/dev/null || echo 0)"
}

echo "=== (а) ВЫКЛ + Правило F ==="
run on_off --no-forecast
echo "=== (б) ВЫКЛ БЕЗ правила (контроль) ==="
run off_off --no-forecast --no-food-gate
echo "=== (в) прогноз + Правило F ==="
run on_on
echo готово