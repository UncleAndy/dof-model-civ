"""Когда город не сообщает выход клетки — брать основу из правил, и говорить об этом (§13.288)."""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

START = "    if not outputs_by_city:"
END = "    outputs = next(iter(outputs_by_city.values()))\n"

NEW = '''    if outputs_by_city:
        outputs = next(iter(outputs_by_city.values()))
    else:
        # Город сообщает выходы только своих клеток, а рабочий часто стоит ВНЕ радиуса
        # (измерено: 6 обращений подряд). Основа выходов — свойство террейна и лежит в
        # правилах мира, поэтому берём её оттуда, а не из наблюдения и не нулём.
        from env.terrain_work_times import TERRAIN_BASE_OUTPUTS

        outputs = TERRAIN_BASE_OUTPUTS.get(str(terrain))
        if outputs is None:
            _port_diag(f"нет основы выходов для террейна {terrain}", None)
            return None
        _port_diag(f"клетка вне радиуса — основа из правил: {terrain} {tuple(outputs)}", None)
'''

text = PATH.read_text(encoding="utf-8")
if "TERRAIN_BASE_OUTPUTS.get(str(terrain))" in text:
    print("уже внесено")
else:
    assert text.count(START) == 1, "начало блока не однозначно"
    assert text.count(END) == 1, "конец блока не однозначен"
    begin = text.index(START)
    finish = text.index(END) + len(END)
    text = text[:begin] + NEW + text[finish:]
    PATH.write_text(text, encoding="utf-8")
    print("внесено")
ast.parse(PATH.read_text(encoding="utf-8"))
print("синтаксис ок")
