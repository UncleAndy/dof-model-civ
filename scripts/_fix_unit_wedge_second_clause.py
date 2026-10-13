"""Второй член правила клина — `is_wedged_here`, а не `is_wedged(context)` (§13.275).

Измерено: `is_wedged` с координатой включал устаревшие семейные отказы и резал
`unit/build_city` в НОВЫХ клетках 176 раз за прогон — обе руки получили счёт 0.0.
Идемпотентно.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

IMPORT_OLD = ("from env.wedged import is_wedged, is_wedged_family, record_success, "
              "record_wedged\n")
IMPORT_NEW = ("from env.wedged import is_wedged_family, is_wedged_here, record_success, "
              "record_wedged\n")

CLAUSE_OLD = '''    try:
        return bool(is_wedged(ctrl, name, context={"position": list(position)}))
    except Exception:  # noqa: BLE001
        return False
'''
CLAUSE_NEW = '''    try:
        # Падало ли ИМЕННО ЗДЕСЬ. Не `is_wedged(context=...)`: он складывает с устаревшими
        # семейными отказами и резал `build_city` в новых клетках — 176 исключений за прогон.
        return bool(is_wedged_here(ctrl, name, position))
    except Exception:  # noqa: BLE001
        return False
'''

text = PATH.read_text(encoding="utf-8")
changed = 0
for old, new in ((IMPORT_OLD, IMPORT_NEW), (CLAUSE_OLD, CLAUSE_NEW)):
    if new in text:
        print("уже внесено")
        continue
    assert text.count(old) == 1, f"якорь не однозначен: {old[:60]}"
    text = text.replace(old, new)
    changed += 1

PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {changed}")

import ast  # noqa: E402
ast.parse(text)
print("синтаксис ок")
