#!/usr/bin/env bash
# Проверка чистоты после остановки прогонов.
echo "=== 1) процессы прогонов/записи ==="
ps -eo pid,etimes,cmd | grep -Ei "v2_play|v2_record|_series_|_rep_seq|_ab_potential|kill_leaked" | grep -v grep || echo "  чисто"

echo
echo "=== 2) ffmpeg ==="
ps -eo pid,etimes,cmd | grep -i ffmpeg | grep -v grep || echo "  чисто"

echo
echo "=== 3) браузеры (всего) ==="
echo "  chromium/playwright процессов: $(ps -eo cmd | grep -ci chrom)"

echo
echo "=== 4) порты стенда 6300-6340 ==="
busy=0
for p in $(seq 6300 6340); do
  if (exec 3<>/dev/tcp/127.0.0.1/"$p") 2>/dev/null; then
    echo "  порт $p ЗАНЯТ"
    busy=$((busy+1))
  fi
done
[ "$busy" -eq 0 ] && echo "  все свободны"

echo
echo "=== 5) живые писатели: контрольные суммы ==="
cd /home/hermes/projects/AI/DOF-MODEL-CIV || exit 1
md5sum knowledge/traces_def4.jsonl knowledge/traces_def5.jsonl \
       knowledge/city_defense_def5.jsonl knowledge/world_def5.json \
       knowledge/city_growth.jsonl 2>/dev/null
sleep 8
echo "--- через 8 секунд ---"
md5sum knowledge/traces_def4.jsonl knowledge/traces_def5.jsonl \
       knowledge/city_defense_def5.jsonl knowledge/world_def5.json \
       knowledge/city_growth.jsonl 2>/dev/null
