#!/usr/bin/env bash
# Серия «рост» (growth1): накопить измеренные эффекты роста (city_work, irrigation, mine, road).
# 5 партий × 150 ходов, свежая база. Никаких изменений модели — только сбор замеров.
#
# ВАЖНО:
#  * Порты стенда — только слоты 6300–6331; «протухший» порт (после убитого прогона) даёт
#    «There is no room for new players». Здесь взяты 6300–6304 (прошлый прогон на них завершился штатно).
#  * Логи civrealm идут в civrealm/logs/{дата}_*.log; файлы сегодняшней даты заняты прогоном
#    пользователя (nobody:nogroup). Обход без sudo — сдвиг даты в имени лога через TZ.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV
P=$PWD
BASE=$P/baselines/world.json
if [ ! -r "$BASE" ]; then echo "СТОП: нет базы $BASE"; exit 2; fi
echo "база: $BASE"; md5sum "$BASE"
cp "$BASE" knowledge/world_growth1.json || { echo "СТОП: копирование базы не удалось"; exit 2; }
SZ=$(stat -c%s knowledge/world_growth1.json)
if [ "$SZ" -lt 1000000 ]; then echo "СТОП: копия базы подозрительно мала ($SZ байт)"; exit 2; fi
echo "база скопирована: $SZ байт"
SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages 2>/dev/null | tr '\n' ':')
export PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP"
export PYTHONWARNINGS=ignore
export V2_STORE=$P/knowledge/world_growth1.json
export V2_TRACE=$P/knowledge/traces_growth1.jsonl
export V2_DEFENSE=$P/knowledge/city_defense_growth1.jsonl
export V2_INCURSION=$P/knowledge/city_incursion_growth1.jsonl
export V2_GROWTH=$P/knowledge/city_growth_growth1.jsonl
export V2_RESULTS=$P/knowledge/results_growth1.jsonl
export V2_TURNS=150
export V2_SEEDS=9260,9261,9262,9263,9264
export V2_PORT_BASE=6300
export TZ=UTC-14
"$P/.venv/bin/python" scripts/v2_play.py > /tmp/growth1.log 2>&1
echo "===== ГОТОВО exit=$? ====="
tail -3 /tmp/growth1.log