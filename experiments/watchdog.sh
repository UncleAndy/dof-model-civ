#!/bin/sh
# Страховка для долгой серии A/B. Молчит, если всё идёт; если драйвер умер —
# поднимает его заново и печатает одну строку (её доставит cron-задача).
cd /home/hermes/projects/AI/DOF-MODEL-CIV || exit 1
done=$(ls -1 experiments/dof-ab-26102026/rounds/*.json 2>/dev/null | wc -l)
[ "$done" -ge 1000 ] && exit 0
pgrep -f "experiments/ab_round[s].py" >/dev/null 2>&1 && exit 0
flock -n experiments/ab.lock true 2>/dev/null || exit 0
echo "драйвер не работал (раундов $done) — перезапускаю"
setsid nohup flock -n experiments/ab.lock .venv/bin/python experiments/ab_rounds.py \
    --start 0 --count 1000 --seed-base 40000 \
    >> experiments/dof-ab-26102026/nohup.log 2>&1 &
exit 0
