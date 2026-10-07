"""Откатить две вставки предыдущего скрипта, попавшие не туда (в судью вместо пропуска),
и зафиксировать честный итог: ключ пропуска по-прежнему (пара), поэтому СИДЫ В ОДНОМ ФАЙЛЕ НЕ СМЕШИВАТЬ.

Слепая правка по признаку «строка с per.setdefault» попала в `cmd_judge`, где `seed` не определён, —
там бы упало. Откат точечный, по полному тексту строки; после — компиляция и печать участков.
"""
from pathlib import Path

AB = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_ab_city_norm.py")
lines = AB.read_text(encoding="utf-8").split("\n")
before = len(lines)
lines = [l for l in lines
         if l.strip() != "done_seed = {}  # полный ключ продолжения: пара И сид"
         and l.strip() != "done_seed[arm] = seed"]
AB.write_text("\n".join(lines), encoding="utf-8")
print(f"удалено строк: {before - len(lines)}")

import py_compile  # noqa: E402
py_compile.compile(str(AB), doraise=True)
print("компиляция: ок")

print("── судья и запись (должны быть без done_seed) ──")
for i, l in enumerate(lines, 1):
    if "per.setdefault" in l or "done" in l and ("= {" in l or "get(" in l or "if " in l):
        print(f"{i:>4}|{l}")
print("── где сравниваются записанные пары с нужными ──")
for i, l in enumerate(lines, 1):
    if "done" in l and ("continue" in l or "in done" in l or "not in done" in l):
        print(f"{i:>4}|{l}")