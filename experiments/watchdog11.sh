#!/bin/sh
# Страховка для серии 11 рук: 100 раундов × 11 партий × 3000 ходов, пул из 4 игр.
# Молчит, если драйвер жив или если раунды уже все собраны.
cd /home/hermes/projects/AI/DOF-MODEL-CIV || exit 1
OUT=experiments/dof-ab-11arms-100x3000
mkdir -p "$OUT"
# раунд 4 играется отдельно на заменённом сиде 200069; когда будет готов —
# переносим его в основную серию, чтобы он вошёл в отчёт
FIX=experiments/dof-ab-11arms-round4/rounds/round_0004.json
DST=$OUT/rounds/round_0004.json
if [ -f "$FIX" ] && [ ! -f "$DST" ]; then
    cp "$FIX" "$DST.tmp" && mv -f "$DST.tmp" "$DST"
    mkdir -p "$OUT/rounds/saves"
    for f in experiments/dof-ab-11arms-round4/rounds/saves/save_round_4_*.sav.zst; do
        [ -f "$f" ] && cp -n "$f" "$OUT/rounds/saves/" 2>/dev/null
    done
    echo "раунд 4 (заменённый сид 200069) перенесён в основную серию"
fi
done=$(ls -1 "$OUT"/rounds/*.json 2>/dev/null | wc -l)
[ "$done" -ge 100 ] && exit 0
pgrep -f "experiments/ab_round[s].py" >/dev/null 2>&1 && exit 0
flock -n experiments/ab11.lock true 2>/dev/null || exit 0
echo "драйвер 11 рук не работал (раундов $done из 100) — перезапускаю"
setsid nohup flock -n experiments/ab11.lock .venv/bin/python experiments/ab_rounds.py \
    --start 0 --count 100 --seed-base 200000 --turns 3000 --aifill 10 --size 2 \
    --par-games 4 --ports 8100,8200,8300,8400 \
    --arms 'd0:none;d1:rot1;d2:rot2;d3:rot3;d4:rot4;d5:rot5;d6:rot6;d7:rot7;d8:rot8;d9:rot9;d10:all' \
    --out "$OUT" --timeout 7200 \
    --set 'set endspaceship disabled' --set 'set endvictory disabled' \
    >> "$OUT/nohup.log" 2>&1 &
exit 0
