#!/usr/bin/env bash
# Непрерывный цикл партий: раунд = 6 партий без DOF + 6 партий с DOF,
# игры идут строго одна за другой (par=1). Останавливается только вручную
# или при нехватке места на диске.
set -u
cd /home/hermes/projects/AI/DOF-MODEL-CIV || exit 1

TURNS=${TURNS:-200}      # шагов на партию (>=150 по требованию)
GAMES=${GAMES:-6}
SIZE=${SIZE:-2}          # малая карта
AIFILL=${AIFILL:-50}     # максимум мест классического набора

r=0
while true; do
  r=$((r + 1))
  free_gb=$(df --output=avail -BG /home/hermes | tail -1 | tr -dc '0-9')
  if [ "${free_gb:-0}" -lt 15 ]; then
    echo "[loop] остановка: свободно всего ${free_gb}G"
    break
  fi
  for arm in none all; do
    base=7600
    [ "$arm" = "all" ] && base=7800
    tag="loop_${arm}_r${r}"
    echo "[loop] раунд $r, рука $arm, порт $base, ходов $TURNS"
    .venv/bin/python deploy/freeciv-dof/run_series.py \
      --tag "$tag" --games "$GAMES" --turns "$TURNS" --aifill "$AIFILL" \
      --size "$SIZE" --par 1 --policy "$arm" --base-port "$base" --timeout 1800 \
      || echo "[loop] $tag: прогон вернул ошибку"
  done
  .venv/bin/python deploy/freeciv-dof/series_report.py \
    --tags "loop_none_r${r},loop_all_r${r}" \
    --md "deploy/freeciv-dof/logs/series/report_loop_r${r}.md" >/dev/null 2>&1 || true
  .venv/bin/python - "$r" <<'PY'
import json, os, sys
r = sys.argv[1]
base = "deploy/freeciv-dof/logs/series"
for arm in ("none", "all"):
    p = f"{base}/loop_{arm}_r{r}.jsonl"
    if not os.path.exists(p):
        print(f"[stats] r{r} {arm}: файла нет")
        continue
    rs = [json.loads(l) for l in open(p)]
    kills = sum(x["units_killed"] for x in rs)
    barb = sum(x.get("barb_units_lost", 0) for x in rs)
    alive = sum(x["alive"] for x in rs)
    seats = sum(x["players"] for x in rs)
    print(f"[stats] r{r} {arm}: партий={len(rs)} убито={kills} варв={barb} "
          f"живых={alive}/{seats}")
PY
done
