#!/bin/sh
# Контрольная рука без DOF на свежих сидах (3000+), чтобы карты не повторяли прежние серии.
set -u
cd "$(dirname "$0")/../.." || exit 1
OUT=deploy/freeciv-dof/logs/clean10
mkdir -p "$OUT"
PY=.venv/bin/python
for g in 0 1 2 3 4 5 6 7 8 9; do
    seed=$((3000 + g * 17))
    tag="clean_none_g${g}"
    echo "[$(date -u +%H:%M:%S)] старт $tag seed=$seed" >> "$OUT/driver_none.log"
    $PY deploy/freeciv-dof/run_series.py --tag "$tag" --games 1 --turns 200 \
        --aifill 50 --size 2 --par 1 --policy none --seed-base "$seed" \
        --base-port 7600 --timeout 1800 >> "$OUT/$tag.log" 2>&1
    rc=$?
    rm -rf "$OUT/$tag"
    docker cp "freeciv-web:/home/docker/dofrun/series/$tag/0" "$OUT/$tag" >/dev/null 2>&1
    echo "[$(date -u +%H:%M:%S)] готов $tag rc=$rc" >> "$OUT/driver_none.log"
done
echo "[$(date -u +%H:%M:%S)] NONE ГОТОВО" >> "$OUT/driver_none.log"
