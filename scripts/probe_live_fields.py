"""Какие поля мир отдаёт по юниту и городу в ЖИВОЙ съёмке (ищем признаки длящихся процессов)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_capture_seed9000.json")
d = json.loads(p.read_text())
obs = d["observation"]

for section in ("unit", "city"):
    recs = obs.get(section) or {}
    keys: set[str] = set()
    for r in recs.values():
        if isinstance(r, dict):
            keys |= set(r.keys())
    print(f"== {section}: {len(recs)} записей, полей {len(keys)} ==")
    print("  ", ", ".join(sorted(keys)))
    for k, r in list(recs.items())[:1]:
        interesting = {kk: vv for kk, vv in r.items()
                       if any(s in kk for s in ("activ", "order", "work", "task", "target",
                                                "progress", "turn", "eta", "stock", "prod"))}
        print(f"   образец {k}: {interesting}")