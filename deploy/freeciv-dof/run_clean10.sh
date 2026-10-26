#!/bin/sh
# 20 последовательных партий: 10 без DOF и 10 с DOF у всех мест.
# Каждая партия — отдельный запуск со своим сидом и своим каталогом данных.
# Параллельность запрещена: par=1, руки идут одна за другой.
set -u
cd "$(dirname "$0")/../.." || exit 1
OUT=deploy/freeciv-dof/logs/clean10
mkdir -p "$OUT"
: > "$OUT/driver.log"
PY=.venv/bin/python

run_one() {
    arm=$1; n=$2; seed=$3; port=$4
    tag="clean_${arm}_g${n}"
    echo "[$(date -u +%H:%M:%S)] старт $tag seed=$seed port=$port" >> "$OUT/driver.log"
    $PY deploy/freeciv-dof/run_series.py --tag "$tag" --games 1 --turns 200 \
        --aifill 50 --size 2 --par 1 --policy "$arm" --seed-base "$seed" \
        --base-port "$port" --timeout 1800 >> "$OUT/$tag.log" 2>&1
    rc=$?
    rm -rf "$OUT/$tag"
    docker cp "freeciv-web:/home/docker/dofrun/series/$tag/0" "$OUT/$tag" >/dev/null 2>&1
    sz=$(du -sh "$OUT/$tag" 2>/dev/null | cut -f1)
    echo "[$(date -u +%H:%M:%S)] готов $tag rc=$rc данные=$sz" >> "$OUT/driver.log"
}

for g in 0 1 2 3 4 5 6 7 8 9; do
    run_one none "$g" $((1000 + g * 17)) 7600
done
for g in 0 1 2 3 4 5 6 7 8 9; do
    run_one all "$g" $((1170 + g * 17)) 7800
done
echo "[$(date -u +%H:%M:%S)] ВСЕГО ГОТОВО" >> "$OUT/driver.log"
