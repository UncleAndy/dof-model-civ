#!/usr/bin/env python3
"""Кто именно умирает в дуэли: сторона, слот, ход, лог.

Собирает по записям прогона игры, где одна сторона сделала 0 решений
(отказ инструмента), и печатает сторону + пути логов, чтобы смотреть причину
в логе клиента, а не гадать.
"""
import json
import sys
from pathlib import Path

summary = Path(sys.argv[1] if len(sys.argv) > 1 else "duel_curiosity_long3.json")
data = json.loads(summary.read_text())
detail = data.get("games_detail") or data.get("games") or []
print("ключи сводки:", list(data.keys()))

dead, clean = [], []
for g in detail:
    a, b = g.get("a") or {}, g.get("b") or {}
    da = float(a.get("decisions_per_turn_mean") or 0)
    db = float(b.get("decisions_per_turn_mean") or 0)
    if not a or not b:
        continue
    if da <= 0 or db <= 0:
        dead.append((g, a, b, da, db))
    else:
        clean.append(g)

print(f"игр в сводке: {len(detail)}   чистых: {len(clean)}   с отказом стороны: {len(dead)}")
print()
print("номер  слот  кто_молчал  ходов  префикс_имени_A  deltaB?  логи")
for g, a, b, da, db in dead:
    who = "A" if da <= 0 else "B"
    mute = a if da <= 0 else b
    alive = b if da <= 0 else a
    print(f"{g.get('game'):>5}  {g.get('slot'):>4}  {who:>9}  {mute.get('turns'):>5}  "
          f"{str(g.get('x_side')):>14}  {alive.get('decisions_per_turn_mean'):>6}  "
          f"{g.get('log_a')} | {g.get('log_b')}")
