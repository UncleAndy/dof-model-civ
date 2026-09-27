#!/usr/bin/env python3
"""Сводка по попыткам дуэли: сторона, ходы, решения, роль (follower?), отказ."""
import glob
import json
import re
from pathlib import Path

rows = []
for f in sorted(glob.glob("/tmp/duel_*_a.json"), key=lambda p: int(re.search(r"duel_(\d+)_", p).group(1))):
    g = int(re.search(r"duel_(\d+)_", f).group(1))
    try:
        ra = list(json.load(open(f))["results"].values())[0][0]
        rb = list(json.load(open(f"/tmp/duel_{g}_b.json"))["results"].values())[0][0]
    except Exception:  # noqa: BLE001
        continue
    fa = fl = 0
    pa, pb = Path(f"/tmp/duel_{g}_a.log"), Path(f"/tmp/duel_{g}_b.log")
    if pa.exists():
        fa = pa.read_text(errors="ignore").count("[follower]")
    if pb.exists():
        fl = pb.read_text(errors="ignore").count("[follower]")
    rows.append((g, float(ra.get("turns") or 0), float(rb.get("turns") or 0),
                 float(ra.get("decisions_per_turn_mean") or 0),
                 float(rb.get("decisions_per_turn_mean") or 0), fa, fl))

print("игра  ходы A/B   реш A/B     follower-строки A/B   диагноз")
for g, ta, tb, da, db, fa, fl in rows:
    if ta < 25 or tb < 25:
        diag = "игра не началась (стенд)"
    elif da <= 0:
        diag = "ОТКАЗ: молчала сторона A (host? follower?)"
    elif db <= 0:
        diag = "ОТКАЗ: молчала сторона B"
    else:
        diag = "ок"
    print(f"{g:>4}  {ta:>3.0f}/{tb:<3.0f}   {da:.2f}/{db:<5.2f}   {fa}/{fl:<19} {diag}")
