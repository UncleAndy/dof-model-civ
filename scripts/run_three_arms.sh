#!/usr/bin/env bash
# Три руки подряд — на портах СТЕНДА 6000–6003 (не 63xx: они нерабочие).
#
#   A  — наши агенты с принципом DoF: четыре ветви, по одной на место
#   A' — контроль: наши агенты со случайной политикой
#   B  — встроенный ИИ мира на четырёх местах + наш хранитель времени без решений
#
# ПРАВИЛО ВХОДА (§13.144): стенд отклоняет имя, для которого учётная запись уже
# есть с другим паролем. Поэтому имена СВЕЖИЕ на каждый запуск — со временем в имени.
#
# Запуск:  PORTS="6000 6001 6002" bash scripts/run_three_arms.sh
set -u

cd "$(dirname "$0")/.." || exit 1
source /home/hermes/v011env.sh 2>/dev/null

TURNS="${TURNS:-150}"
MATCH_TIMEOUT="${MATCH_TIMEOUT:-20000}"
PORTS="${PORTS:-6000 6001 6002}"
STAMP="$(date +%H%M)"

DOF_POLICIES="dof_defensive dof_economic dof_technological dof_expansionist"
SETTLE="--duel --settle 0"

stop_ours() { .venv/bin/python scripts/_stop_own_games.py >/dev/null 2>&1 || true; }

# ждём признака, что партия началась; 0 — началась, 2 — вход отклонён, 1 — не дождались
wait_started() {
  local glob="$1" limit="${2:-200}" t=0
  while [ "$t" -lt "$limit" ]; do
    if grep -qhE "держава взята" $glob 2>/dev/null; then return 0; fi
    if grep -qhE "Log in rejected|Could not authenticate" $glob 2>/dev/null; then return 2; fi
    sleep 10; t=$((t + 10))
  done
  return 1
}

arm_dof() {
  local P="$1" n=0 pol
  echo "══ A: принцип DoF, слот $P ══"
  for pol in $DOF_POLICIES; do
    n=$((n + 1))
    .venv/bin/python baselines/run_real_tournament.py --only "$pol" --episodes 1 \
      --turns "$TURNS" --no-auto-port --port "$P" --output "/tmp/A_dof_${P}_${pol}.json" \
      $SETTLE --timeout "$MATCH_TIMEOUT" --username "d${STAMP}${n}" --aifill 0 --minp 4 \
      --begin_turn_timeout 380 --server_timeout 120 --follower_take_player true \
      >"/tmp/A_dof_${P}_${pol}.log" 2>&1 &
    echo "   $pol: имя d${STAMP}${n}, pid $!"
  done
}

arm_random() {
  local P="$1" n=0
  echo "══ A': случайная политика, слот $P ══"
  for n in 1 2 3 4; do
    .venv/bin/python baselines/run_real_tournament.py --only random --episodes 1 \
      --turns "$TURNS" --no-auto-port --port "$P" --output "/tmp/A_rand_${P}_$n.json" \
      $SETTLE --timeout "$MATCH_TIMEOUT" --username "r${STAMP}${n}" --aifill 0 --minp 4 \
      --begin_turn_timeout 380 --server_timeout 120 --follower_take_player true \
      >"/tmp/A_rand_${P}_$n.log" 2>&1 &
    echo "   место $n: имя r${STAMP}${n}, pid $!"
  done
}

arm_builtin() {
  local P="$1"
  echo "══ B: встроенный ИИ, слот $P ══"
  .venv/bin/python baselines/run_real_tournament.py --only no-op --episodes 1 \
    --turns "$TURNS" --no-auto-port --port "$P" --output "/tmp/B_ai_${P}.json" \
    --timeout "$MATCH_TIMEOUT" --username "b${STAMP}1" --aifill 5 --minp 1 \
    --begin_turn_timeout 380 --server_timeout 120 --follower_take_player true \
    >"/tmp/B_ai_${P}.log" 2>&1 &
  echo "   хранитель времени: имя b${STAMP}1, pid $!"
}

read -r -a PLIST <<<"$PORTS"
idx=0
for arm in dof random builtin; do
  P="${PLIST[$idx]:-}"
  if [ -z "$P" ]; then echo "портов в списке больше нет"; exit 1; fi
  idx=$((idx + 1))
  stop_ours
  case "$arm" in
    dof)     arm_dof "$P" ;;
    random)  arm_random "$P" ;;
    builtin) arm_builtin "$P" ;;
  esac
  wait_started "/tmp/*_${P}_*.log" 200
  case "$?" in
    0) echo "   рука $arm ПОШЛА на слоте $P — ждём её конца"; wait; echo "   рука $arm закрыта" ;;
    2) echo "   рука $arm: вход ОТКЛОНЁН на слоте $P"; stop_ours ;;
    *) echo "   рука $arm: партия на слоте $P не началась за отведённое время"; stop_ours ;;
  esac
done
echo "ТРИ РУКИ ОТРАБОТАНЫ"