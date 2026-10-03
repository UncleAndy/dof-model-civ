#!/usr/bin/env bash
# Смоук §10.116 (вариант 1а): произойдёт ли выбор produce_Settlers и основание 2-го города.
# 2 партии × 45 ходов. База из baselines/ (защита от пустой базы).
# ВАЖНО: порты стенда — только слоты 6300–6331 (вне диапазона → Connection could not be established).
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
BASE=$P/baselines/world.json
if [ ! -r "$BASE" ]; then echo "СТОП: нет базы $BASE"; exit 2; fi
cp "$BASE" knowledge/world_settlers2.json || { echo "СТОП: копирование базы не удалось"; exit 2; }
SZ=$(stat -c%s knowledge/world_settlers2.json)
if [ "$SZ" -lt 1000000 ]; then echo "СТОП: копия базы подозрительно мала ($SZ байт)"; exit 2; fi
echo "база скопирована: $SZ байт"
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
export V2_STORE=$P/knowledge/world_settlers2.json
export V2_TRACE=$P/knowledge/traces_settlers2.jsonl
export V2_DEFENSE=$P/knowledge/city_defense_settlers2.jsonl
export V2_INCURSION=$P/knowledge/city_incursion_settlers2.jsonl
export V2_GROWTH=$P/knowledge/city_growth_settlers2.jsonl
export V2_RESULTS=$P/knowledge/results_settlers2.jsonl
export V2_TURNS=45
export V2_SEEDS=9240,9247
export V2_PORT_BASE=6324
"$P/.venv/bin/python" scripts/v2_play.py > /tmp/settlers2.log 2>&1
echo "===== ГОТОВО exit=$? ====="
tail -3 /tmp/settlers2.log
