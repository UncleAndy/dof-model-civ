"""Разбор трассы записи: что выбиралось и что было в коридоре (для отчёта по видео)."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_record6.jsonl")
chosen: collections.Counter = collections.Counter()
cands: collections.Counter = collections.Counter()
risk = 0
escape = 0
n = 0
for line in path.open():
    line = line.strip()
    if not line:
        continue
    r = json.loads(line)
    n += 1
    for c in r.get("кандидаты", []) or []:
        eff = c.get("эффект") or []
        cands[eff[0] if eff else "?"] += 1
    ch = r.get("выбрано") or {}
    chosen[ch.get("goal") or ch.get("kind") or "?"] += 1
    rk = r.get("риск") or {}
    if isinstance(rk, dict) and (rk.get("цена") or 0) > 0:
        risk += 1
    if ch.get("goal") == "escape":
        escape += 1

print(f"файл: {path}")
print(f"решений: {n}")
print("ВЫБРАНО:", dict(chosen.most_common(10)))
print("В КОРИДОРЕ:", dict(cands.most_common(10)))
print(f"решений с ценой риска > 0: {risk}; выбран выход (escape): {escape}")