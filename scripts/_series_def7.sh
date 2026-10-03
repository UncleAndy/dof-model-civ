#!/usr/bin/env bash
# §10.113/§10.114/§10.115: прикрытие города + отпор + сближение с источником.
# 8 партий × 150 ходов. База берётся из baselines/ (knowledge/world.json — симлинк,
# из-под учётки hermes НЕ виден). Защита: без валидной базы прогон НЕ стартует.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
BASE=$P/baselines/world.json
if [ ! -r "$BASE" ]; then echo "СТОП: нет базы $BASE"; exit 2; fi
cp "$BASE" knowledge/world_def7.json || { echo "СТОП: копирование базы не удалось"; exit 2; }
SZ=$(stat -c%s knowledge/world_def7.json)
if [ "$SZ" -lt 1000000 ]; then echo "СТОП: копия базы подозрительно мала ($SZ байт)"; exit 2; fi
echo "база скопирована: $SZ байт"
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
export V2_STORE=$P/knowledge/world_def7.json
export V2_TRACE=$P/knowledge/traces_def7.jsonl
export V2_DEFENSE=$P/knowledge/city_defense_def7.jsonl
export V2_INCURSION=$P/knowledge/city_incursion_def7.jsonl
export V2_GROWTH=$P/knowledge/city_growth_def7.jsonl
export V2_RESULTS=$P/knowledge/results_def7.jsonl
export V2_TURNS=150
export V2_SEEDS=9240,9241,9242,9243,9244,9245,9246,9247
export V2_PORT_BASE=6324
"$P/.venv/bin/python" scripts/v2_play.py > /tmp/def7.log 2>&1
echo "===== ГОТОВО exit=$? ====="
tail -3 /tmp/def7.log