"""Заставить запись открытий писать строку на каждый ход, даже когда новых клеток нет.

Найденная ветка: `if prev is None or prev_turn is None or prev_turn == turn: return` и затем
`if not fresh: return` — то есть файл появлялся ТОЛЬКО когда множество открытых клеток изменилось.
А оно не менялось: под туманом видно ~9 клеток из 4056, и они те же. Отсюда «запись молчит» —
и это было неотличимо от «открывать было нечего», что для замера недопустимо.

Теперь строка пишется на каждый новый ход: сколько открыто всего и сколько новых (в том числе ноль).
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
text = RUN.read_text(encoding="utf-8")

OLD = """    if prev is None or prev_turn is None or prev_turn == turn:
        return
    fresh = sorted(now - prev)
    if not fresh:
        return
"""
NEW = """    if prev_turn == turn:
        return
    fresh = sorted(now - prev) if prev is not None else []
"""
if OLD not in text:
    print("ожидаемая ветка не найдена — правка не применена")
else:
    text = text.replace(OLD, NEW, 1)

OLD_W = """        fh.write(json.dumps({"ход": turn, "новых_клеток": len(fresh), "клетки": rows},
                            ensure_ascii=False) + "\\n")
"""
NEW_W = """        fh.write(json.dumps({"ход": turn, "открыто_всего": len(now), "новых_клеток": len(fresh),
                             "клетки": rows}, ensure_ascii=False) + "\\n")
    print(f"    [открытия] ход {turn}: открыто всего {len(now)}, новых {len(fresh)}", flush=True)
"""
if OLD_W in text:
    text = text.replace(OLD_W, NEW_W, 1)
    RUN.write_text(text, encoding="utf-8")
    print("запись открытий теперь пишет строку на каждый ход")
else:
    print("место записи строки не найдено — правка не применена")

import py_compile  # noqa: E402
py_compile.compile(str(RUN), doraise=True)
print("компиляция: ок")