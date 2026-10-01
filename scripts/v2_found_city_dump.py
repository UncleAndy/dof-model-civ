"""Показать, что именно записано в кандидатах found_city (числа, а не догадки)."""
from __future__ import annotations

import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_record6.jsonl")
shown = 0
kinds: dict = {}
for line in path.open():
    line = line.strip()
    if not line:
        continue
    rec = json.loads(line)
    for c in rec.get("кандидаты") or []:
        eff = c.get("эффект") or []
        if eff and eff[0] == "found_city":
            kinds[tuple(sorted(c.keys()))] = kinds.get(tuple(sorted(c.keys())), 0) + 1
            if shown < 4:
                shown += 1
                print(json.dumps(c, ensure_ascii=False)[:600])
print("наборы ключей у found_city-кандидатов:", {k: v for k, v in list(kinds.items())[:3]})