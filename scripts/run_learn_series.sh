#!/usr/bin/env bash
# §10.32: способность к самообучению. Две ветви склада фактов, один дизайн игр.
#   ХОЛОД  — склад пуст, 5 серий подряд (накопление и перенос между сериями)
#   ТЁПЛЫЙ — копия склада проекта (13 типов), 3 серии (цена переноса сразу)
# Пишется <output>.learn.jsonl по каждой игре: покрытие, точность, поправки, решения.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
GAMES=10
TURNS=30

one() {   # one <склад> <метка серии>
  local store="$1" tag="$2"
  rm -f "/tmp/learn_${tag}.json" "/tmp/learn_${tag}.json.learn.jsonl"
  DOF_MEASURED_FACTS="$store" .venv/bin/python baselines/run_real_tournament.py \
    --episodes "$GAMES" --turns "$TURNS" --aifill 6 --only dof_defensive \
    --dump-candidates 2 --output "/tmp/learn_${tag}.json" \
    > "/tmp/learn_${tag}.log" 2>&1
  echo "  ${tag}: rc=$?  записей обучения $(wc -l < "/tmp/learn_${tag}.json.learn.jsonl" 2>/dev/null || echo 0)"
}

echo "=== ХОЛОД: склад пуст, 5 серий x ${GAMES} игр x ${TURNS} ходов ==="
rm -f /tmp/learn_cold.json
for s in 1 2 3 4 5; do one /tmp/learn_cold.json "cold_s${s}"; done
echo "  склад после ХОЛОДА: $(grep -c '\"kind\"' /tmp/learn_cold.json 2>/dev/null || echo 0) типов"

echo "=== ТЁПЛЫЙ: копия склада проекта, 3 серии ==="
cp measured_facts.json /tmp/learn_warm.json
for s in 1 2 3; do one /tmp/learn_warm.json "warm_s${s}"; done
echo готово