#!/usr/bin/env bash
# Рука DoF: четыре наших агента, по одной ветви принципа DoF на место.
#
# ВАЖНО (§13.142): порт годен ТОЛЬКО для первой партии после рождения движка.
# Поэтому порт нельзя «проверять» короткой пробой — проба его и сжигает.
# Здесь проверка одна: запускаем настоящую руку и смотрим, взяты ли державы.
#
# Запуск:  PORTS="6314 6315 6316" bash scripts/launch_dof_arm.sh
set -u

cd "$(dirname "$0")/.." || exit 1
source /home/hermes/v011env.sh 2>/dev/null

POLICIES="dof_defensive dof_economic dof_technological dof_expansionist"
TURNS="${TURNS:-150}"
MATCH_TIMEOUT="${MATCH_TIMEOUT:-20000}"
PORTS="${PORTS:-6314 6315 6316 6317 6318 6319 6320}"

stop_ours() { .venv/bin/python scripts/_stop_own_games.py >/dev/null 2>&1 || true; }

try_port() {
  local P="$1" n=0 pol rej nations
  echo "── слот $P ──"
  for pol in $POLICIES; do
    n=$((n + 1))
    .venv/bin/python baselines/run_real_tournament.py \
      --only "$pol" --episodes 1 --turns "$TURNS" \
      --no-auto-port --port "$P" --output "/tmp/AdofG_${P}_${pol}.json" \
      --duel --settle 0 --timeout "$MATCH_TIMEOUT" \
      --username "g$n" --aifill 0 --minp 4 \
      --begin_turn_timeout 380 --server_timeout 120 \
      --follower_take_player true >"/tmp/AdofG_${P}_${pol}.log" 2>&1 &
    echo "   $pol: имя g$n, pid $!"
  done
  sleep 200
  rej=$(grep -hcE "Log in rejected|Could not authenticate" /tmp/AdofG_${P}_*.log 2>/dev/null | paste -sd+ - | bc 2>/dev/null || echo 0)
  nations=$(grep -h "держава взята" /tmp/AdofG_${P}_*.log 2>/dev/null | wc -l)
  echo "   отказов входа: $rej   держав взято: $nations"
  if [ "${nations:-0}" -ge 1 ]; then
    echo "РУКА ПОШЛА на слоте $P (держав $nations, отказов $rej)"
    echo "$P" >/tmp/dof_arm_slot
    return 0
  fi
  echo "   слот $P не принял — снимаю и пробую следующий"
  stop_ours
  sleep 10
  return 1
}

for P in $PORTS; do
  if try_port "$P"; then exit 0; fi
done
echo "ГОДНЫЙ СЛОТ НЕ НАЙДЕН"
exit 1
