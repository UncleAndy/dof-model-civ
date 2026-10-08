"""Проба §13.78: отзывается ли счёт мира на основание города и на рост (по прошедшим партиям).

Стенд не занимается. Для каждой записи ищутся ходы, где выросло число городов (основание) или
размер какого-то города (рост), и берётся изменение счёта за тот же ход; контроль — прочие ходы.
"""
from __future__ import annotations

import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parent.parent
KN = ROOT / "knowledge"


def cities_of(row):
    ids = {e.get("id") for e in (row.get("разбивка") or []) if e.get("вид") == "city"}
    out = {}
    for cid in ids:
        rec = (row.get("city_output") or {}).get(cid) or {}
        out[cid] = rec.get("размер") if isinstance(rec, dict) else None
    return out


def num(v):
    return v if isinstance(v, (int, float)) else None


events_found = []
events_grow = []
others = []

runs = sorted(KN.glob("live_trace_952*.jsonl")) + sorted(KN.glob("live_trace_953*.jsonl"))
print(f"записей: {len(runs)}")
for path in runs:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if len(rows) < 3:
        continue
    f = g = o = 0
    for prev_row, row in zip(rows, rows[1:]):
        s0, s1 = num(prev_row.get("счёт_мира")), num(row.get("счёт_мира"))
        if s0 is None or s1 is None:
            continue
        d = s1 - s0
        c0, c1 = cities_of(prev_row), cities_of(row)
        founded = len(c1) > len(c0)
        grew = any(c1[k] is not None and c0.get(k) is not None and c1[k] > c0[k] for k in c1)
        if founded:
            events_found.append(d)
            f += 1
        elif grew:
            events_grow.append(d)
            g += 1
        else:
            others.append(d)
            o += 1
    print(f"  {path.name}: основание {f}, рост {g}, прочих {o}")

print("\n── изменения счёта за ход ──")
for name, vals in (("основание города", events_found), ("рост города", events_grow),
                   ("прочие ходы (контроль)", others)):
    if vals:
        print(f"  {name}: событий {len(vals)}, медиана {statistics.median(vals)}, "
              f"среднее {round(sum(vals) / len(vals), 3)}, от {min(vals)} до {max(vals)}")
    else:
        print(f"  {name}: событий 0")

print("\n── правило решения из §13.78 ──")
med_other = statistics.median(others) if others else None
for name, vals in (("основание", events_found), ("рост", events_grow)):
    if len(vals) >= 3 and med_other is not None:
        m = statistics.median(vals)
        verdict = "установлена" if m > med_other else "НЕ установлена"
        print(f"  {name}: событий {len(vals)}, медиана {m} против контроля {med_other} → {verdict}")
    else:
        print(f"  {name}: событий {len(vals)} — меньше трёх, связь НЕ установлена")
