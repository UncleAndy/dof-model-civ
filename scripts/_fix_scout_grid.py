"""Исправить чтение карты в оснастке разведки: `obs["map"]["status"]` приходит массивом,
`not grid` на массиве даёт ValueError (поймано пилотом, плечо A упало с выходом 1 — не прошло тихо).

Приведение к обычным спискам целых: заодно снимает вопросы булева чтения элементов.
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
OLD = """    units = ((info or {}).get("available_actions") or {}).get("unit") or {}
    grid = ((obs or {}).get("map") or {}).get("status")
    if not units or not grid:
        return None
    xsize = int(((obs or {}).get("map") or {}).get("xsize") or 0)
    unseen = [(y, x) for y, row in enumerate(grid) for x, s in enumerate(row or []) if s != _OPEN]
"""
NEW = """    units = ((info or {}).get("available_actions") or {}).get("unit") or {}
    raw = ((obs or {}).get("map") or {}).get("status")
    if not units or raw is None:
        return None
    # Карта приходит массивом: булево чтение массива запрещено (`ValueError` на `not grid`),
    # поэтому сразу приводим к спискам целых — и вопросы «истинности» снимаются вместе с ним.
    grid = [[int(s) for s in row] for row in raw]
    xsize = int(((obs or {}).get("map") or {}).get("xsize") or 0)
    unseen = [(y, x) for y, row in enumerate(grid) for x, s in enumerate(row) if s != _OPEN]
"""
text = RUN.read_text(encoding="utf-8")
if "raw = ((obs or {}).get(\"map\") or {}).get(\"status\")" in text:
    print("уже исправлено")
else:
    if OLD not in text:
        raise SystemExit("тело _scout_action не найдено — правка не применена")
    RUN.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("исправлено: карта приводится к спискам целых")

import py_compile  # noqa: E402
py_compile.compile(str(RUN), doraise=True)
print("компиляция: ок")