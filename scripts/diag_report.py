#!/usr/bin/env python3
"""Диагностика дуэли: по каждой попытке — что сказал клиент и что предложил сервер."""
import glob
import json
import re
from pathlib import Path

for f in sorted(glob.glob("/tmp/duel_*_a.json"), key=lambda p: int(re.search(r"duel_(\d+)_", p).group(1))):
    g = int(re.search(r"duel_(\d+)_", f).group(1))
    for side in ("a", "b"):
        rec_path = Path(f"/tmp/duel_{g}_{side}.json")
        log_path = Path(f"/tmp/duel_{g}_{side}.log")
        try:
            rec = list(json.loads(rec_path.read_text())["results"].values())[0][0]
        except Exception:  # noqa: BLE001
            continue
        log = log_path.read_text(errors="ignore") if log_path.exists() else ""
        thaws = [ln.strip() for ln in log.splitlines() if "[thaw" in ln]
        empties = [ln.strip() for ln in log.splitlines() if "пусто" in ln]
        verdict = "ОТКАЗ" if float(rec.get("decisions_per_turn_mean") or 0) <= 0 else "ок"
        if verdict == "ок" and float(rec.get("turns") or 0) >= 25:
            continue
        print(f"=== игра {g}, сторона {side.upper()}  [{verdict}]  "
              f"ходов={rec.get('turns')} реш/ход={rec.get('decisions_per_turn_mean')} "
              f"пустых ходов={rec.get('empty_action_turns')}")
        for ln in thaws[:2]:
            print("    ", ln)
        for ln in empties[:3]:
            print("    ", ln)
