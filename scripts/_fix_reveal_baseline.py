"""Считать «новые клетки» от прошлого ЗАПИСАННОГО хода, а не от предыдущего вызова в этом же ходу.

Дефект: `_record_reveals` вызывается несколько раз за ход (решений за ход много), поэтому множество
прошлого вызова обновлялось прямо в этом ходу, и прирост всегда выходил нулевым (9 → 22 → 32 открытых,
а «новых 0»). Правильно: хранить множество на конец записанного хода и сравнивать с ним.
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
text = RUN.read_text(encoding="utf-8")
OLD = """    prev, prev_turn = _REVEAL["set"], _REVEAL["turn"]
    _REVEAL["set"], _REVEAL["turn"] = now, turn
    if prev_turn == turn:
        return
    fresh = sorted(now - prev) if prev is not None else []
"""
NEW = """    if _REVEAL["turn"] == turn:
        return                      # в этом ходу уже записали — второй раз не считаем
    prev, prev_turn = _REVEAL["set"], _REVEAL["turn"]
    fresh = sorted(now - prev) if prev is not None else []
    _REVEAL["set"], _REVEAL["turn"] = now, turn
"""
if OLD not in text:
    print("место сравнения не найдено — правка не применена")
else:
    RUN.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("сравнение идёт от прошлого записанного хода")

import py_compile  # noqa: E402
py_compile.compile(str(RUN), doraise=True)
print("компиляция: ок")