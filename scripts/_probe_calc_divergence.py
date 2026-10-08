"""Проба §13.79: наш индекс против индекса ядра по набору расчёта — по строкам трассы.

Ничего не решает и не правит: печатает числа, чтобы расхождение было видно, а не предполагалось.
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
KN = ROOT / "knowledge"


def pick() -> pathlib.Path:
    if len(sys.argv) > 1:
        return pathlib.Path(sys.argv[1])
    files = sorted(KN.glob("live_trace_*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1]


path = pick()
rows = []
for line in path.read_text(encoding="utf-8").splitlines():
    if line.strip():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass

print(f"запись: {path.name}, ходов: {len(rows)}")
if not rows:
    print("ходов нет — судить нечего")
    raise SystemExit(0)

pairs = [(r.get("индекс"), r.get("индекс_ядра")) for r in rows]
diff = [(a, b) for a, b in pairs if isinstance(a, (int, float)) and isinstance(b, (int, float))]

print("\n── по ходам ──")
print("  ход | индекс | в расчёте | индекс ядра | причина набора")
for r in rows:
    why = (r.get("причина_набора") or "—")
    print(f'  {r.get("ход"):>3} | {r.get("индекс")!s:>7} | {r.get("в_расчёте")!s:>9} | '
          f'{r.get("индекс_ядра")!s:>11} | {why[:60]}')

if diff:
    ours = [a for a, _ in diff]
    core = [b for _, b in diff]
    agree = sum(1 for a, b in diff if abs(a - b) < 1e-9)
    print("\n── итог ──")
    print(f"  строк с обоими числами: {len(diff)}; совпало: {agree}; разошлось: {len(diff) - agree}")
    print(f"  наш индекс:    медиана {statistics.median(ours)}, от {min(ours)} до {max(ours)}")
    print(f"  индекс ядра:   медиана {statistics.median(core)}, от {min(core)} до {max(core)}")
    if agree != len(diff):
        worst = max(diff, key=lambda p: abs(p[0] - p[1]))
        print(f"  наибольшее расхождение: наш {worst[0]} против ядра {worst[1]}")
else:
    print("\n── итог: обоих чисел нет ни в одной строке ──")

names = {r.get("причина_набора") for r in rows if r.get("причина_набора")}
sizes = [r.get("в_расчёте") for r in rows if isinstance(r.get("в_расчёте"), int)]
print(f"\n  пустых наборов: {sum(1 for s in sizes if s == 0)} из {len(sizes)}")
print(f"  названных состояний: {sorted(names) if names else 'нет'}")
