"""Сводка серии: по каждому матчу — агент, порт и счёт из итога стенда."""
from __future__ import annotations

import re
import sys
from collections import defaultdict

LOG = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dof_parity_series.log"

re_agent = re.compile(r"^\s+(\S+)\s+Reset with port: (\d+)")
re_field = re.compile(r"(\w+)=(-?\d+)")

rows: list[tuple[str, dict[str, int]]] = []
pending_agent: str | None = None
with open(LOG, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        m = re_agent.match(line)
        if m:
            pending_agent = m.group(1)
            continue
        if "счёт по категориям" in line and pending_agent:
            fields = {k: int(v) for k, v in re_field.findall(line)}
            rows.append((pending_agent, fields))
            pending_agent = None

by_agent: dict[str, list[dict[str, int]]] = defaultdict(list)
for agent, fields in rows:
    by_agent[agent].append(fields)

print(f"матчей разобрано: {len(rows)}")
print(f"{'агент':<20}{'n':>3}{'счёт':>9}{'военных':>10}{'городов':>9}{'насел.':>8}{'юнитов':>8}")
for agent in sorted(by_agent):
    vals = by_agent[agent]
    n = len(vals)
    avg = lambda key: sum(v.get(key, 0) for v in vals) / n
    print(f"{agent:<20}{n:>3}{avg('score'):>9.2f}{avg('military_units'):>10.1f}"
          f"{avg('cities'):>9.1f}{avg('population'):>8.1f}{avg('units_built'):>8.1f}")
