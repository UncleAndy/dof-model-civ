"""Проба §13.77 (часть «счёт»): счёт мира против городов, размера и DoF — на реальных трассах.

Источник — записи сегодняшних прогонов (`knowledge/live_trace_952*.jsonl`), стенд не нужен.
Печатается по каждому прогону: ходов, счёт в начале/конце, число городов, размеры и DoF городов;
и сводка «счёт против числа городов» по всем прогонам вместе. Сцена указывается, потому что
счёт — величина мира и принадлежит своей сцене.
"""
from __future__ import annotations

import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parent.parent
KN = ROOT / "knowledge"

runs = sorted(KN.glob("live_trace_952*.jsonl")) + sorted(KN.glob("live_trace_970*.jsonl"))
print(f"найдено трасс: {len(runs)}")

summary = []
for path in runs:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        print(f"\n{path.name}: записей нет")
        continue

    def cities(row):
        out = []
        for e in row.get("разбивка") or []:
            if e.get("вид") == "city":
                size = None
                co = (row.get("city_output") or {}).get(e.get("id")) or {}
                if isinstance(co, dict):
                    size = co.get("размер")
                out.append((e.get("id"), size, e.get("dof"), e.get("вклад"), co.get("выход_щитов")))
        return out

    first, last = rows[0], rows[-1]
    c_first, c_last = cities(first), cities(last)
    scores = [r.get("счёт_мира") for r in rows if isinstance(r.get("счёт_мира"), (int, float))]
    print(f"\n{path.name}")
    print(f"  ходов: {len(rows)} | счёт: {scores[0] if scores else '-'} → "
          f"{scores[-1] if scores else '-'} (медиана {statistics.median(scores) if scores else '-'})")
    print(f"  городов: {len(c_first)} → {len(c_last)}")
    for cid, size, dof, vklad, shields in c_last[:6]:
        print(f"    {cid}: размер {size}, DoF {dof}, вклад {vklad}, выход щитов {shields}")
    if scores and c_last:
        summary.append((path.name, len(rows), len(c_last), scores[-1],
                        statistics.median([c[2] for c in c_last if isinstance(c[2], (int, float))] or [0])))

print("\n── сводка: счёт против числа городов ──")
print(f"{'трасса':>46} {'ходов':>6} {'городов':>8} {'счёт':>6} {'медиана DoF гор.':>17}")
for name, turns, nc, sc, mdof in sorted(summary, key=lambda x: x[2]):
    print(f"{name:>46} {turns:>6} {nc:>8} {sc:>6} {mdof:>17.4f}")
