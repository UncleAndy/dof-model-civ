#!/usr/bin/env python
"""Разбивка §10.32 по сериям: решения/ход, счёт, число срезов кандидатов."""
import json
import statistics

def line(tag, path):
    try:
        d = json.load(open(path))
    except FileNotFoundError:
        print(f"{tag}: нет файла {path}")
        return
    eps = list(d["results"].values())[0]
    dec = [float(e.get("decisions_per_turn_mean") or 0) for e in eps]
    sc = [float(e.get("score_cum") or 0) for e in eps]
    turns = [int(e.get("turns") or 0) for e in eps]
    acts = [int(e.get("actions_issued") or 0) for e in eps]
    print(f"{tag}: игр {len(eps)}  реш/ход {statistics.mean(dec):.2f}  "
          f"действий {sum(acts)}  счёт {sum(sc):.0f} (на игру "
          f"{sum(sc)/max(1,len(eps)):.2f})  коротких {sum(1 for t in turns if t < 30)}")

for s in range(1, 6):
    line(f"ХОЛОД s{s}", f"/tmp/learn_cold_s{s}.json")
for s in range(1, 4):
    line(f"ТЁПЛ s{s} ", f"/tmp/learn_warm_s{s}.json")