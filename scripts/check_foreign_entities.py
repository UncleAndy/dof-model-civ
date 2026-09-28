#!/usr/bin/env python
"""Проверка: входят ли ЧУЖИЕ юниты/города в набор сущностей и в индекс DoF.

Как проверяется: извлекатель строит сущности по ВСЕМ записям наблюдения (фильтра по
владельцу в коде нет), поэтому число сущностей `ent=` из лога (результат извлечения)
обязано быть НЕ меньше, чем «наши + чужие юниты + города» из среза. Печатаем пары
«ход: наши/чужие юниты, города, ent из лога» — чужое видно там, где `чужих > 0`.
"""
import json
import re
import sys
from collections import defaultdict

dump_path, log_path = sys.argv[1], sys.argv[2]
ENT = re.compile(r"\[turn (\d+)/\d+ ent=(\d+)")
rows = [json.loads(x) for x in open(dump_path, encoding="utf-8") if x.strip()]
# лог: берём первый матч (первая секция)
text = open(log_path, encoding="utf-8").read()
sections = text.split("Reset with port")[1:]
section = sections[0] if sections else text
ent_by_turn = {}
for m in ENT.finditer(section):
    ent_by_turn[int(m.group(1))] = int(m.group(2))

ep = sorted({r.get("эпизод") for r in rows})[0]
game = sorted([r for r in rows if r.get("эпизод") == ep],
              key=lambda r: r.get("turn_played") or 0)
print(f"файл {dump_path}, матч {ep}; в логе {log_path} последний ent={max(ent_by_turn.values()) if ent_by_turn else '?'}")
print(f"{'ход':>4} {'наши':>5} {'чужие':>6} {'города':>7} {'наши+чужие+города':>18} "
      f"{'ent(лог)':>9}  (ent печатается каждые 10 ходов)")
prev_ent = None
for r in game:
    myu = len(r.get("my_units") or [])
    fu = len(r.get("foreign_units") or [])
    cities = len(r.get("my_cities") or []) + len(r.get("foreign_cities") or [])
    turn = r.get("turn")
    if turn in ent_by_turn:
        prev_ent = ent_by_turn[turn]
    mark = "  ← чужое видно" if fu else ""
    print(f"{turn:>4} {myu:>5} {fu:>6} {cities:>7} {myu+fu+cities:>18} "
          f"{str(prev_ent):>9}{mark}")