#!/usr/bin/env bash
# §10.34: где умирает движение. Нужны обе стороны: меню сервера (что предлагают) и
# список кандидатов прогноза (что остаётся после фильтров). 4 игры × 8 ходов.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/moveprobe.json /tmp/moveprobe.json.state.jsonl
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 4 --turns 8 --aifill 6 --only dof_defensive \
  --dump-candidates 8 --dump-state 8 --output /tmp/moveprobe.json \
  > /tmp/moveprobe.log 2>&1
echo "rc=$?  срезов кандидатов: $(grep -c '\[кандидаты\]' /tmp/moveprobe.log 2>/dev/null || echo 0)"
echo готово