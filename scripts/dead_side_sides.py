#!/usr/bin/env python3
"""Сторона отказа по записям в /tmp для заданных номеров игр."""
import json
import sys

games = [int(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else []
print("игра  сторона_X  молчал  ходов  решений A/B   логи")
for g in games:
    try:
        ra = list(json.load(open(f"/tmp/duel_{g}_a.json"))["results"].values())[0][0]
        rb = list(json.load(open(f"/tmp/duel_{g}_b.json"))["results"].values())[0][0]
    except Exception as exc:  # noqa: BLE001
        print(g, "нет записей:", exc)
        continue
    da = float(ra.get("decisions_per_turn_mean") or 0)
    db = float(rb.get("decisions_per_turn_mean") or 0)
    who = "A" if da <= 0 else ("B" if db <= 0 else "-")
    print(f"{g:>4}  {'B' if g % 2 == 0 else 'A':>9}  {who:>6}  {ra.get('turns'):>5}  "
          f"{da:.2f}/{db:.2f}   порты {ra.get('port')}/{rb.get('port')}  "
          f"startxy {ra.get('start_xy')} / {rb.get('start_xy')}")
