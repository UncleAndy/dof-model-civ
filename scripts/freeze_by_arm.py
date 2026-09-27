#!/usr/bin/env python3
"""Замерзание (0 решений за матч) по вариантам X (любопытство ВКЛ) и Y (ВЫКЛ).

Зачем. Игры с нулём решений переигрывались как «отказ инструмента», но замер
показал, что это законный исход правила «нет строгого улучшения — не действовать».
Если замерзание бьёт по одному варианту чаще, чем по другому, то переигровка
СМЕЩАЕТ выборку, и вердикт очной ставки надо пересматривать.

Вариант определяется конфигурацией, а не стороной: стороны переставляются (--swap),
поэтому вариант X — это сторона B в чётных играх и сторона A в нечётных. Какая
сторона какую политику играла, подтверждается заголовком её лога
(«Curiosity bonus ... ON/OFF»), а не догадкой.

    python scripts/freeze_by_arm.py --games 10
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return None
    for _agent, records in (payload.get("results") or {}).items():
        for rec in records:
            return rec
    return None


def curiosity_of(log: Path) -> str:
    if not log.exists():
        return "?"
    for line in log.read_text(errors="ignore").splitlines():
        if "Curiosity bonus" in line:
            return "ON" if line.strip().endswith("ON") else "OFF"
    return "?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--min-turns", type=int, default=15)
    args = ap.parse_args()

    rows = []
    for g in range(1, args.games + 1):
        recs = {s: load(Path(f"/tmp/duel_{g}_{s}.json")) for s in ("a", "b")}
        if not recs["a"] or not recs["b"]:
            continue
        turns = min(float(recs[s].get("turns") or 0) for s in ("a", "b"))
        dec = {s: float(recs[s].get("decisions_per_turn_mean") or 0) for s in ("a", "b")}
        cur = {s: curiosity_of(Path(f"/tmp/duel_{g}_{s}.log")) for s in ("a", "b")}
        if turns < args.min_turns:
            rows.append((g, "стенд без игры", "-", dec, cur))
            continue
        frozen = [s for s in ("a", "b") if dec[s] <= 0.0]
        if frozen:
            rows.append((g, "замерзание", frozen[0].upper(), dec, cur))
        else:
            rows.append((g, "ок", "-", dec, cur))

    print("=" * 84)
    print("ЗАМЕРЗАНИЕ (0 решений) ПО ВАРИАНТАМ")
    print("=" * 84)
    print(" игра  итог              сторона  решений A/B   любопытство A/B")
    for g, why, side, dec, cur in rows:
        print(f"{g:>5}  {why:<17} {side:>7}  {dec['a']:.2f}/{dec['b']:.2f}      "
              f"{cur['a']}/{cur['b']}")

    frozen_rows = [r for r in rows if r[1] == "замерзание"]
    on = sum(1 for _g, _w, side, _d, cur in frozen_rows
             if cur[side.lower()] == "ON")
    off = sum(1 for _g, _w, side, _d, cur in frozen_rows
              if cur[side.lower()] == "OFF")
    print()
    print(f"  замерзаний всего: {len(frozen_rows)}  "
          f"(из них любопытство ВКЛ: {on}, ВЫКЛ: {off}, неизвестно: "
          f"{len(frozen_rows) - on - off})")
    if frozen_rows:
        print("  ВАЖНО: замерзание нельзя выбрасывать как брак инструмента — "
              "это исход правила")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
