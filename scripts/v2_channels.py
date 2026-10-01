"""Какие каналы наблюдений есть в базе и что в них (для расчёта достижимого DoF города)."""
from __future__ import annotations

import json
import pathlib
import statistics
import sys

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world.json")
data = json.loads(path.read_text())
obs = data.get("observed") or {}
for key, vals in sorted(obs.items()):
    n = len(vals)
    nums = [v.get("значение") for v in vals if isinstance(v, dict) and isinstance(v.get("значение"), (int, float))]
    med = statistics.median(nums) if nums else None
    sample = vals[0] if vals else None
    print(f"{key}: n={n}, медиана={med}")
    print(f"   пример: {json.dumps(sample, ensure_ascii=False)[:200]}")
    if key in ("city_size_buildable", "dof_city", "dof_city_reach"):
        by: dict = {}
        for v in vals:
            if isinstance(v, dict) and isinstance(v.get("размер"), int):
                by.setdefault(v["размер"], []).append(v.get("значение"))
        for size in sorted(by):
            print(f"   размер {size}: n={len(by[size])}, медиана {statistics.median(by[size])}")