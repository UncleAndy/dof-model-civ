"""Разбор смоука §10.116: выбрано ли produce_Settlers и основаны ли города.

Запуск: .venv/bin/python scripts/_settlers_verdict.py [traces] [results]
"""
from __future__ import annotations

import collections
import json
import sys

TR = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_settlers2.jsonl"
RES = sys.argv[2] if len(sys.argv) > 2 else "knowledge/results_settlers2.jsonl"

lines = open(TR, encoding="utf-8").read().splitlines()
turns = []
for l in lines:
    try:
        turns.append(json.loads(l).get("ход"))
    except Exception:
        turns.append(None)
starts = [i for i in range(len(turns)) if turns[i] == 1 and (i == 0 or turns[i - 1] != 1)]
starts.append(len(turns))

goals = collections.Counter()
produced = collections.Counter()
found_hits = []
for pi in range(len(starts) - 1):
    for i in range(starts[pi], starts[pi + 1]):
        try:
            d = json.loads(lines[i])
        except Exception:
            continue
        ch = d.get("выбрано") or {}
        goals[ch.get("goal") or "(нет)"] += 1
        for s in (ch.get("steps") or []):
            a = s.get("action") or ""
            if a.startswith("produce_"):
                produced[a[len("produce_"):]] += 1
        if ch.get("goal") == "found_city":
            found_hits.append((pi + 1, d.get("ход")))

print("=== ЦЕЛИ (выбрано) ===")
for g, n in goals.most_common():
    print(f"  {g:12s} {n}")
print("\n=== ПРОИЗВОДСТВО (выбрано) ===")
for k, v in produced.most_common(20):
    print(f"  {k}: {v}")
print(f"\n=== ОСНОВАНИЯ ГОРОДОВ ===")
for party, h in found_hits:
    print(f"  партия {party}: найден город на ходу {h}")
if not found_hits:
    print("  (оснований нет)")

print("\n=== ИСХОДЫ ===")
try:
    for l in open(RES, encoding="utf-8"):
        r = json.loads(l)
        print(f"  сид {r['seed']}: ходов {r['ходов_сыграно']} счёт {r['счёт']} "
              f"городов {r['городов']} юнитов {r['юнитов']} простоев {r['ходов_без_действия']}")
except FileNotFoundError:
    print("  (нет файла результатов)")
