#!/usr/bin/env python
"""Почему шаги не проходят: распределение «ценность клетки минус ценность места».

Читает строки `[движение]` (числа по шагам) и показывает, сколько шагов проходит при
разных правилах отбора: как сейчас (по ценности клетки на месте), с раскрытием и при
базовой линии «0» вместо ценности клетки города.
"""
import re
import statistics
import sys
from collections import Counter

STEP = re.compile(
    r"шаг: (\S+) → \((\d+), (\d+)\): ценность ([\d.]+), раскрытие ([\d.]+), "
    r"на месте ([\d.]+), пройдёт по ценности (\w+), с раскрытием (\w+)")
MOVE = re.compile(r"\[движение\] единиц (\d+), предложено шагов (\d+), "
                  r"отброшено по ценности (\d+), оставлено (\d+)")

path = sys.argv[1]
steps = []
moves_summary = []
for line in open(path, encoding="utf-8"):
    m = STEP.search(line)
    if m:
        steps.append({"юнит": m.group(1), "куда": (int(m.group(2)), int(m.group(3))),
                      "ценность": float(m.group(4)), "раскрытие": float(m.group(5)),
                      "на_месте": float(m.group(6))})
    m2 = MOVE.search(line)
    if m2:
        moves_summary.append(tuple(int(x) for x in m2.groups()))
print(f"строк со шагами: {len(steps)}; сводок движения: {len(moves_summary)}")
if not steps:
    raise SystemExit("нет данных")
delta = [s["ценность"] - s["на_месте"] for s in steps]
print(f"разница «ценность − на месте»: мин {min(delta):+.2f}, "
      f"медиана {statistics.median(delta):+.2f}, макс {max(delta):+.2f}")
print(f"  доля шагов, проходящих по ценности (delta > 0): "
      f"{sum(1 for d in delta if d > 0)} из {len(delta)}")
print(f"  доля шагов с раскрытием > 0: "
      f"{sum(1 for s in steps if s['раскрытие'] > 0)} из {len(steps)}")
zero_base = [s for s in steps if s["ценность"] > 0.0]
print(f"  при базовой линии «0» вместо ценности клетки города прошло бы: "
      f"{len(zero_base)} из {len(steps)}")
vals = sorted(s["ценность"] for s in steps)
print(f"  ценности клеток шага: мин {vals[0]:.2f}, медиана "
      f"{statistics.median(vals):.2f}, макс {vals[-1]:.2f}")
print(f"  ценности клеток «на месте»: "
      f"{dict(Counter(round(s['на_месте'], 2) for s in steps).most_common(5))}")
if moves_summary:
    print("  сводки: единиц/шагов/отброшено/оставлено (первые 6):")
    for row in moves_summary[:6]:
        print("   ", row)