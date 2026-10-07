"""Проверка готовности правки §13.66 БЕЗ её применения (файл не меняется).

Читает константы из apply-скрипта (он под точкой входа, поэтому импорт безопасен) и
проверяет: старая ветка встречается ровно один раз, точка вставки однозначна, а результат
замены разбирается как синтаксис.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("_apply1366", ROOT / "scripts" / "_apply_risk_zero_reason.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)            # точка входа защищена: правка НЕ применяется

text = mod.TARGET.read_text(encoding="utf-8")
n_old = text.count(mod.OLD)
n_anchor = text.count("def risk_with_reason(")
already = "def foreign_powers(" in text
print("вхождений старой ветки:", n_old, "(нужно 1)")
print("точек вставки «def risk_with_reason(»:", n_anchor, "(нужно 1)")
print("уже применено:", already)

if not already and n_old == 1 and n_anchor == 1:
    future = text.replace(mod.OLD, mod.NEW)
    future = future.replace("def risk_with_reason(",
                            mod.HELPER.lstrip("\n") + "\ndef risk_with_reason(", 1)
    ast.parse(future)
    print("синтаксис будущего результата: ок")
    print("новая формулировка появится:", "угрозы есть, они просто не наблюдены" in future)
    print("Готово к применению после закрытия опыта.")
else:
    print("Применять нельзя без разбора (см. числа выше).")
    sys.exit(0 if already else 1)
