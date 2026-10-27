#!/bin/sh
# Страховка для длинного прогона: 100 раундов × 3000 ходов, пул из 4 партий.
# Победы отключены (endspaceship/endvictory disabled). Молчит, если драйвер жив.
cd /home/hermes/projects/AI/DOF-MODEL-CIV || exit 1
OUT=experiments/dof-ab-100x3000
mkdir -p "$OUT"
done=$(ls -1 "$OUT"/rounds/*.json 2>/dev/null | wc -l)
[ "$done" -ge 100 ] && exit 0
pgrep -f "experiments/ab_round[s].py" >/dev/null 2>&1 && exit 0
flock -n experiments/ab100.lock true 2>/dev/null || exit 0
echo "драйвер 100x3000 не работал (раундов $done) — перезапускаю"
setsid nohup flock -n experiments/ab100.lock .venv/bin/python experiments/ab_rounds.py \
    --start 0 --count 100 --seed-base 200000 --turns 3000 --aifill 10 --size 2 \
    --par-games 4 --ports 8100,8200,8300,8400 \
    --out experiments/dof-ab-100x3000 --timeout 7200 \
    --set 'set endspaceship disabled' --set 'set endvictory disabled' \
    >> "$OUT/nohup.log" 2>&1 &
exit 0
