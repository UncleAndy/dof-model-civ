#!/usr/bin/env python3
"""Частота отказов в дуэли: по причинам и по сторонам.

Нужен как планка «до/после»: правка инструмента без числа — не правка.
Различает три исхода попытки, которые снаружи выглядят одинаково:

* «отказ стороны» — сторона сделала 0.00 решений при полном числе ходов
  (инструмент, не политика);
* «стенд не дал игры» — ходов меньше порога, мир пустой;
* «ок».

    python scripts/failure_rate.py --log /tmp/duel_ctrls.log --pattern '/tmp/duel_{g}_{s}.json'
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path


def load(path: str):
    p = Path(path)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None
    for _agent, records in (payload.get("results") or {}).items():
        for rec in records:
            return rec
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="/tmp/duel_ctrls.log")
    ap.add_argument("--pattern", default="/tmp/duel_{g}_{s}.json")
    ap.add_argument("--min-turns", type=int, default=15)
    args = ap.parse_args()

    numbers = sorted({int(m.group(1)) for m in
                      (re.match(r".*duel_(\d+)_[ab]\.json", f) for f in
                       glob.glob(args.pattern.format(g="*", s="*")))
                      if m})
    if not numbers:
        print("нет записей — частоту считать не по чему (это «данных нет»)")
        return 0

    dead = {"A": 0, "B": 0}
    short = ok = 0
    rows = []
    for g in numbers:
        recs = {s: load(args.pattern.format(g=g, s=s)) for s in ("a", "b")}
        if not recs["a"] or not recs["b"]:
            continue
        turns = min(float(recs[s].get("turns") or 0) for s in ("a", "b"))
        dec = {s: float(recs[s].get("decisions_per_turn_mean") or 0) for s in ("a", "b")}
        if turns < args.min_turns:
            short += 1
            why = "стенд не дал игры"
        elif 0.0 in (dec["a"], dec["b"]):
            side = "A" if dec["a"] <= 0 else "B"
            dead[side] += 1
            why = f"ОТКАЗ стороны {side}"
        else:
            ok += 1
            why = "ок"
        rows.append((g, turns, dec["a"], dec["b"], why))

    total = len(rows)
    n_dead = dead["A"] + dead["B"]
    print("=" * 78)
    print("ЧАСТОТА ОТКАЗОВ ДУЭЛИ (планка «до/после»)")
    print("=" * 78)
    for g, turns, da, db, why in rows:
        print(f"  попытка {g:>3}: ходов {turns:>3.0f}  решений {da:.2f}/{db:.2f}  {why}")
    print()
    print(f"  попыток: {total}   ок: {ok}   отказ стороны: {n_dead} "
          f"(A {dead['A']} / B {dead['B']})   стенд без игры: {short}")
    if total:
        print(f"  доля отказов стороны: {n_dead / total:.0%} попыток, "
              f"{n_dead / (ok + n_dead) if ok + n_dead else 0:.0%} от состоявшихся игр")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
