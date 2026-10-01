"""Показать структуру первой записи трассы (ключи и срезы значений)."""
from __future__ import annotations

import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_record6.jsonl")
with path.open() as fh:
    first = fh.readline()
rec = json.loads(first)
print("КЛЮЧИ:", list(rec.keys()))
for key, val in rec.items():
    text = json.dumps(val, ensure_ascii=False)
    print(f"  {key}: {text[:220]}")