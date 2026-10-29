#!/bin/sh
# Страховка для серии частичного DOF: 30 раундов × 3000 ходов, пул из 4 партий,
# четыре руки раунда (1/9, 3/7, 7/3, 9/1 мест по правилу DOF). Победы отключены.
# Молчит, если драйвер жив.
cd /home/hermes/projects/AI/DOF-MODEL-CIV || exit 1
OUT=experiments/dof-ab-partial-30x3000
mkdir -p "$OUT"
done=$(ls -1 "$OUT"/rounds/*.json 2>/dev/null | wc -l)
[ "$done" -ge 30 ] && exit 0
pgrep -f "experiments/ab_round[s].py" >/dev/null 2>&1 && exit 0
flock -n experiments/abpartial.lock true 2>/dev/null || exit 0
echo "драйвер partial-30x3000 не работал (раундов $done) — перезапускаю"
setsid nohup flock -n experiments/abpartial.lock .venv/bin/python experiments/ab_rounds.py \
    --start 0 --count 30 --seed-base 200000 --turns 3000 --aifill 10 --size 2 \
    --par-games 4 --ports 8100,8200,8300,8400 \
    --arms 'd1:rot1;d3:rot3;d7:rot7;d9:rot9' \
    --out experiments/dof-ab-partial-30x3000 --timeout 7200 \
    --set 'set endspaceship disabled' --set 'set endvictory disabled' \
    >> "$OUT/nohup.log" 2>&1 &
exit 0
