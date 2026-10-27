#!/bin/sh
# Замер предельной длины партии: прогоны с растущим endturn на одном движке.
# Для каждой длины фиксируем время, дошедший ход, причину конца и память контейнера.
set -u
cd "$(dirname "$0")/.." || exit 1
OUT=experiments/length
mkdir -p "$OUT"
: > "$OUT/result.tsv"
PY=.venv/bin/python

for T in "$@"; do
    tag="len${T}"
    rm -f "deploy/freeciv-dof/logs/series/${tag}.jsonl"
    mem0=$(docker stats --no-stream --format '{{.MemUsage}}' freeciv-web | cut -d'/' -f1)
    t0=$(date +%s)
    $PY deploy/freeciv-dof/run_series.py --tag "$tag" --games 1 --turns "$T" \
        --aifill 10 --size 2 --par 1 --policy all --seed-base 70000 \
        --base-port 7600 --timeout 14400 >> "$OUT/${tag}.log" 2>&1
    rc=$?
    t1=$(date +%s)
    mem1=$(docker stats --no-stream --format '{{.MemUsage}}' freeciv-web | cut -d'/' -f1)
    save=$(docker exec freeciv-web sh -lc "ls /home/docker/dofrun/series/${tag}/0/*.sav.zst 2>/dev/null | head -1")
    turn="?"
    reason="?"
    if [ -n "$save" ]; then
        docker cp "freeciv-web:$save" "/tmp/${tag}.sav.zst" >/dev/null 2>&1
        zstd -dc "/tmp/${tag}.sav.zst" > "/tmp/${tag}.sav" 2>/dev/null
        turn=$(grep -m1 '^turn=' "/tmp/${tag}.sav" | cut -d= -f2)
        reason=$(grep -m1 '^reason=' "/tmp/${tag}.sav" | cut -d= -f2-)
        cp "/tmp/${tag}.sav.zst" "$OUT/${tag}.sav.zst"
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$T" "$((t1 - t0))" "$turn" "$reason" "$mem0" "$mem1" >> "$OUT/result.tsv"
    echo "T=$T rc=$rc время=$((t1 - t0))с ход=$turn причина=$reason память $mem0 -> $mem1" >> "$OUT/progress.log"
    docker exec freeciv-web sh -lc "rm -rf /home/docker/dofrun/series/${tag}" >/dev/null 2>&1
done
echo DONE >> "$OUT/progress.log"
