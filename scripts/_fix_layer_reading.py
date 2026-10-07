"""Устойчивое чтение слоёв карты: элемент слоя может быть не числом, а массивом.

Дефект: `int(v)` на элементе слоя падал (`TypeError: only 0-dimensional arrays can be converted`).
Причина — `extras` и родственные слои приходят не плоскими числами. Правильное поведение: неизвестное
значение писать как `None` (мы его не разобрали), а не падать и не подменять нулём — ноль означал бы
«там ничего», а это ровно та ошибка, которой быть не должно.
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
text = RUN.read_text(encoding="utf-8")
OLD = """    def layer(name):  # noqa: ANN001
        arr = m.get(name)
        return [[int(v) for v in col] for col in arr] if arr is not None else None
"""
NEW = """    def layer(name):  # noqa: ANN001
        \"\"\"Слой карты как список столбцов; неразобранный элемент — `None`, а не ноль и не падение.\"\"\"
        arr = m.get(name)
        if arr is None:
            return None
        out = []
        for col in arr:
            row = []
            for v in col:
                try:
                    row.append(int(v))
                except Exception:  # noqa: BLE001
                    row.append(None)
            out.append(row)
        return out
"""
if OLD not in text:
    print("чтение слоя не найдено — правка не применена")
else:
    RUN.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("чтение слоёв сделано устойчивым")

import py_compile  # noqa: E402
py_compile.compile(str(RUN), doraise=True)
print("компиляция: ок")