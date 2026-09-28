#!/usr/bin/env bash
# Серия §10.29, второй заход: назвать ТРИГГЕР голода.
# Прибор дополнен: выход клетки под нашими юнитами/городом и выбранные за ход
# действия (-trace). Матчей больше, ходов меньше: голод приходит на 3–6-м ходу.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/famine_off.json /tmp/famine_off.json.state.jsonl
rm -f /tmp/famine_on.json  /tmp/famine_on.json.state.jsonl

echo "=== ВЫКЛ, 12 игр x 14 ходов, 6 игроков, со срезами и трассой действий ==="
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 12 --turns 14 --aifill 6 --only dof_defensive --no-forecast --trace \
  --dump-state 14 --output /tmp/famine_off.json > /tmp/famine_off.log 2>&1
echo "ВЫКЛ rc=$?  строк срезов: $(wc -l < /tmp/famine_off.json.state.jsonl 2>/dev/null || echo 0)"

echo "=== ПРОГНОЗ, 12 игр x 14 ходов, 6 игроков ==="
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 12 --turns 14 --aifill 6 --only dof_defensive --trace \
  --dump-state 14 --output /tmp/famine_on.json > /tmp/famine_on.log 2>&1
echo "ПРОГНОЗ rc=$?  строк срезов: $(wc -l < /tmp/famine_on.json.state.jsonl 2>/dev/null || echo 0)"
echo "готово"