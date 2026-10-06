"""Разбор серии A/B §10.116: что реально выбрано в каждом плече.

Считает по трейсам: выбранные шаги produce_* (по типам), цели found_city, число партий.
"""
from __future__ import annotations

import collections
import json
import sys


def analyze(path: str) -> dict:
    chosen_prod = collections.Counter()
    goals = collections.Counter()
    parties = 0
    prev_turn = None
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("ход")
        if t == 1 and prev_turn != 1:
            parties += 1
        prev_turn = t
        ch = d.get("выбрано") or {}
        goals[ch.get("goal") or "(нет)"] += 1
        for s in (ch.get("steps") or []):
            a = s.get("action") or ""
            if a.startswith("produce_"):
                chosen_prod[a[len("produce_"):]] += 1
    return {"parties": parties, "prod": chosen_prod, "goals": goals}


for name in ("A", "B"):
    r = analyze(f"knowledge/traces_ab116_{name}.jsonl")
    print(f"=== плечо {name} (партий {r['parties']}) ===")
    print("  выбрано производство:", dict(r["prod"].most_common(12)))
    print("  цели:", dict(r["goals"].most_common(10)))