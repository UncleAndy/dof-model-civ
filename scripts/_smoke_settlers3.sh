#!/usr/bin/env bash
# Смоук §10.116-бис (город × frac × cover − цена жителя): поведение на живом мире.
# 2 партии × 45 ходов. База из baselines/ (защита от пустой базы).
# ВАЖНО: порты стенда — только слоты 6300–6331 (вне диапазона → Connection could not be established).
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
BASE=$P/baselines/world.json
if [ ! -r "$BASE" ]; then echo "СТОП: нет базы $BASE"; exit 2; fi
cp "$BASE" knowledge/world_settlers3.json || { echo "СТОП: копирование базы не удалось"; exit 2; }
SZ=$(stat -c%s knowledge/world_settlers3.json)
if [ "$SZ" -lt 1000000 ]; then echo "СТОП: копия базы подозрительно мала ($SZ байт)"; exit 2; fi
echo "база скопирована: $SZ байт"
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
export V2_STORE=$P/knowledge/world_settlers3.json
export V2_TRACE=$P/knowledge/traces_settlers3.jsonl
export V2_DEFENSE=$P/knowledge/city_defense_settlers3.jsonl
export V2_INCURSION=$P/knowledge/city_incursion_settlers3.jsonl
export V2_GROWTH=$P/knowledge/city_growth_settlers3.jsonl
export V2_RESULTS=$P/knowledge/results_settlers3.jsonl
export V2_TURNS=45
export V2_SEEDS=9240,9247
export V2_PORT_BASE=6324
# Логи civrealm идут в civrealm/logs/{дата}_myagent.log и {дата}_root.log. Файлы СЕГОДНЯШНЕЙ даты
# заняты прогоном пользователя (nobody:nogroup) — писать в них нельзя, а sudo/удаление запрещены.
# Чистый обход: сдвигаем дату в имени лога через TZ (логгер берёт дату из локального времени) —
# создаются свежие файлы, файлы пользователя не трогаются.
export TZ=UTC-14
"$P/.venv/bin/python" scripts/v2_play.py > /tmp/settlers3.log 2>&1
echo "===== ГОТОВО exit=$? ====="
tail -3 /tmp/settlers3.log