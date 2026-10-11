#!/usr/bin/env bash
# Рука DoF: четыре наших агента, по одной ветви принципа DoF на место.
# Подбирает порт сам: пул выдаёт и испорченные, а стенд отклоняет вход на слоте,
# где уже побывала партия. Правило пробы: не начинать, если вход отклонён.
#
# Запуск (в фоне):  bash scripts/launch_dof_arm.sh
set -u

cd "$(dirname "$0")/.." || exit 1
source /home/hermes/v011env.sh 2>/dev/null

POLICIES="dof_defensive dof_economic dof_technological dof_expansionist"
TURNS="${TURNS:-150}"
MATCH_TIMEOUT="${MATCH_TIMEOUT:-20000}"

stop_ours() { .venv/bin/python scripts/_stop_own_games.py >/dev/null 2>&1 || true; }

try_port() {
  local P="$1" n=0 pol log
  echo "── слот $P ──"
  for pol in $POLICIES; do
    n=$((n + 1))
    log="/tmp/AdofF_${P}_${pol}.log"
    .venv/bin/python baselines/run_real_tournament.py \
      --only "$pol" --episodes 1 --turns "$TURNS" \
      --no-auto-port --port "$P" --output "/tmp/AdofF_${P}_${pol}.json" \
      --duel --settle 0 --timeout "$MATCH_TIMEOUT" \
      --username "f$n" --aifill 0 --minp 4 \
      --begin_turn_timeout 380 --server_timeout 120 \
      --follower_take_player true >"$log" 2>&1 &
    echo "   $pol: имя f$n, pid $!"
  done
  sleep 170
  local rej nations
  rej=$(grep -hcE "Log in rejected|Could not authenticate" /tmp/AdofF_${P}_*.log 2>/dev/null | paste -sd+ - | bc 2>/dev/null || echo 0)
  nations=$(grep -h "держава взята" /tmp/AdofF_${P}_*.log 2>/dev/null | wc -l)
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

stop_ours
for P in 6313 6319 6320 6321 6322 6323 6324 6325; do
  if try_port "$P"; then exit 0; fi
done
echo "ГОДНЫЙ СЛОТ НЕ НАЙДЕН"
exit 1
