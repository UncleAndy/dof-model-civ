"""Полный разбор одного кандидата found_city из трассы: проекция и все числа."""
from __future__ import annotations

import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_cityfix.jsonl")
with path.open() as fh:
    for line in fh:
        rec = json.loads(line)
        for c in rec.get("кандидаты") or []:
            eff = c.get("эффект") or []
            if eff and eff[0] == "found_city":
                print(json.dumps(c, ensure_ascii=False, indent=1))
                print("--- решение:", json.dumps(rec.get("выбрано"), ensure_ascii=False)[:200])
                print("--- индекс:", rec.get("индекс"), "риск:", json.dumps(rec.get("риск"), ensure_ascii=False))
                raise SystemExit(0)