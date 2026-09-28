#!/usr/bin/env bash
# §10.34 V3: состав индекса и цена «беговой дорожки производства».
# 2 игры × 30 ходов — к концу игры у агента 12–16 юнитов на клетке города.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
rm -f /tmp/indexcomp.json /tmp/indexcomp.json.state.jsonl
.venv/bin/python baselines/run_real_tournament.py \
  --episodes 2 --turns 30 --aifill 6 --only dof_defensive \
  --dump-state 30 --output /tmp/indexcomp.json > /tmp/indexcomp.log 2>&1
echo "rc=$?  срезов индекса: $(grep -c 'индекс DoF' /tmp/indexcomp.log 2>/dev/null || echo 0)"
echo готово