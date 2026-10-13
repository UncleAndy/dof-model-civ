"""Рядом с `is_wedged` — семейный запрет для действия, которое НИ РАЗУ не удалось (§13.274).

Зачем отдельная функция, а не правка `is_wedged`: его семантика закреплена тестом
`test_success_resolves_unscoped_history_without_erasing_it` («успех в одной позиции не
разрешает другие позиции») — это нарочное решение, и мы его не трогаем.

Зачем она нужна: измерено на живом реестре — `unit/plant` (26 отказов в 25 разных
клетках, 0 успехов) позиционным правилом НЕ режется, потому что каждая клетка падала
один раз; а `unit/build_city` (3 отказа, 37 успехов) режется семейным правилом, хотя
работает постоянно. Обязательное условие «успехов ноль» разделяет их идеально.

Правка идемпотентна.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "env" / "wedged.py"

ANCHOR = '''def _new_wedge_entry(ctrl_type, action_name, turn, context):
'''

NEW_FUNC = '''def is_wedged_family(ctrl_type: str, action_name: str) -> bool:
    """Семейный запрет ТОЛЬКО для действия, которое ни разу не удалось (§13.274).

    Почему это отдельное правило, а не `is_wedged` без координат: там порог считается по
    накопленным отказам и успех в одной позиции не разрешает другие — нарочное решение,
    закреплённое тестом. Здесь же вопрос другой: «стоит ли вообще рассматривать это
    действие». Ответ — нет, если оно падало неоднократно и НИ РАЗУ не прошло.

    Ни один параметр не вводится: порог тот же, что у семейного правила (`>= 2`), а новое
    условие — «успехов ноль». На живых данных оно разделяет случаи точно:
    `unit/plant` — 26 отказов, 0 успехов → резать; `unit/build_city` — 3 отказа и 37
    успехов → играть; `city/city_work` — 53 отказа без координат, 0 успехов → резать.
    """
    if not ctrl_type or not action_name:
        return False
    entry = load_wedged().get(key_of(ctrl_type, action_name))
    if not entry:
        return False
    if int(entry.get("successes", 0) or 0) > 0:
        return False
    return _active_failures(str(entry.get("reason", "timeout")),
                            int(entry.get("seen", 1)),
                            int(entry.get("resolved_seen", 0)))


'''

text = PATH.read_text(encoding="utf-8")
if "def is_wedged_family(" in text:
    print("функция уже есть")
else:
    assert text.count(ANCHOR) == 1, "якорь не однозначен"
    text = text.replace(ANCHOR, NEW_FUNC + ANCHOR)
    PATH.write_text(text, encoding="utf-8")
    print("функция добавлена")

import ast  # noqa: E402
ast.parse(text)
print("синтаксис ок")
