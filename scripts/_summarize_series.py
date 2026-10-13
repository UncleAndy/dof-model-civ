"""Сводка серии: по каждой партии — рука, что её играла, и счёт из итога стенда.

Метка руки печатается ОДИН раз на несколько партий, поэтому партия приписывается
последней объявленной руке, а не сбрасывается после первого счёта (иначе из девяти
партий в сводку попадало три).
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict

LOG = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dof_want_series.log"

re_agent = re.compile(r"^\s+(\S+)\s+Reset with port: (\d+)")
re_field = re.compile(r"(\w+)=(-?\d+)")

rows: list[tuple[str, dict[str, int]]] = []
agent: str | None = None
with open(LOG, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        m = re_agent.match(line)
        if m:
            agent = m.group(1)
            continue
        if "счёт по категориям" in line and agent:
            rows.append((agent, {k: int(v) for k, v in re_field.findall(line)}))

by_agent: dict[str, list[dict[str, int]]] = defaultdict(list)
for name, fields in rows:
    by_agent[name].append(fields)

print(f"партий разобрано: {len(rows)}")
print(f"{'рука':<20}{'n':>3}{'счёт':>9}{'военных':>10}{'городов':>9}{'насел.':>8}{'юнитов':>8}")
for name in sorted(by_agent):
    vals = by_agent[name]
    n = len(vals)
    avg = lambda key: sum(v.get(key, 0) for v in vals) / n
    print(f"{name:<20}{n:>3}{avg('score'):>9.2f}{avg('military_units'):>10.1f}"
          f"{avg('cities'):>9.1f}{avg('population'):>8.1f}{avg('units_built'):>8.1f}")
if rows:
    n = len(rows)
    print(f"{'ИТОГО':<20}{n:>3}"
          f"{sum(v.get('score', 0) for _, v in rows)/n:>9.2f}"
          f"{sum(v.get('military_units', 0) for _, v in rows)/n:>10.1f}"
          f"{sum(v.get('cities', 0) for _, v in rows)/n:>9.1f}")
