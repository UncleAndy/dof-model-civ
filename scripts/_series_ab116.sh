#!/usr/bin/env bash
# §10.116 A/B: «поселенец = город, без горизонта» (плечо A) против прежней формулы (плечо B).
#
# ПРОТОКОЛ (объявлен ДО данных):
#   Вопрос: даёт ли §10.116 выигрыш в исходе партии?
#   Плечи: A — механизм ВКЛ (по умолчанию); B — ВЫКЛ (V2_NO_SETTLER_CITY=1).
#   Дизайн: 10 пар, сиды 9250–9259, по 150 ходов; порты A 6300–6309, B 6310–6319.
#   База: baselines/world.json (одна и та же, md5 сверяется в начале), копия на каждое плечо.
#   Мера: итоговый счёт партии, опубликованный миром; партии не выбрасываются (нет счёта → 0).
#   Вердикт (§10.95/§10.104): медиана попарных (A−B) ≥ 2 очка И знаковый тест p < 0.05 (n=10 → ≥9/10)
#                            И медиана разностей ≥ 10% медианы |B| (снимается при медиане B = 0).
#
# ВАЖНО: порты стенда — только слоты 6300–6331 (вне диапазона → Connection could not be established).
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
BASE=$P/baselines/world.json
if [ ! -r "$BASE" ]; then echo "СТОП: нет базы $BASE"; exit 2; fi
echo "база: $BASE"; md5sum "$BASE"
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore

run_arm () {   # $1=имя  $2=порт  $3=off_flag(0/1)
  local name=$1 port=$2 off=$3
  cp "$BASE" "knowledge/world_ab116_${name}.json" || { echo "СТОП: копия базы ($name)"; return 2; }
  local sz; sz=$(stat -c%s "knowledge/world_ab116_${name}.json")
  if [ "$sz" -lt 1000000 ]; then echo "СТОП: копия базы ($name) мала ($sz)"; return 2; fi
  export V2_STORE=$P/knowledge/world_ab116_${name}.json
  export V2_TRACE=$P/knowledge/traces_ab116_${name}.jsonl
  export V2_DEFENSE=$P/knowledge/city_defense_ab116_${name}.jsonl
  export V2_INCURSION=$P/knowledge/city_incursion_ab116_${name}.jsonl
  export V2_GROWTH=$P/knowledge/city_growth_ab116_${name}.jsonl
  export V2_RESULTS=$P/knowledge/results_ab116_${name}.jsonl
  export V2_TURNS=150
  export V2_SEEDS=9250,9251,9252,9253,9254,9255,9256,9257,9258,9259
  export V2_PORT_BASE=$port
  if [ "$off" = "1" ]; then export V2_NO_SETTLER_CITY=1; else unset V2_NO_SETTLER_CITY; fi
  echo "== плечо $name: порты $port..$((port+9)), V2_NO_SETTLER_CITY=${V2_NO_SETTLER_CITY:-<нет>} =="
  "$P/.venv/bin/python" scripts/v2_play.py > "/tmp/ab116_${name}.log" 2>&1
  echo "== плечо $name: exit=$? =="
}

run_arm A 6300 0
run_arm B 6310 1

echo "===== ГОТОВО ====="
.venv/bin/python scripts/_verdict_ab116.py
