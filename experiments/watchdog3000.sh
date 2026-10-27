#!/bin/sh
# Страховка для серии 3000 ходов: 10 раундов по три партии (no DOF / DOF / 50-50),
# победы отключены (endspaceship/endvictory disabled). Молчит, если драйвер жив.
cd /home/hermes/projects/AI/DOF-MODEL-CIV || exit 1
OUT=experiments/dof-ab-3000-test
done=$(ls -1 "$OUT"/rounds/*.json 2>/dev/null | wc -l)
[ "$done" -ge 10 ] && exit 0
pgrep -f "experiments/ab_round[s].py" >/dev/null 2>&1 && exit 0
flock -n experiments/ab3000.lock true 2>/dev/null || exit 0
echo "драйвер 3000 не работал (раундов $done) — перезапускаю"
setsid nohup flock -n experiments/ab3000.lock .venv/bin/python experiments/ab_rounds.py \
    --start 0 --count 10 --seed-base 120000 --turns 3000 --aifill 10 --size 2 \
    --out experiments/dof-ab-3000-test --timeout 7200 \
    --set 'set endspaceship disabled' --set 'set endvictory disabled' \
    >> "$OUT/nohup.log" 2>&1 &
exit 0
