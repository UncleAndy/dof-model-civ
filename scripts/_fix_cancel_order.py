"""Отмена собственного приказа получает ШТРАФ (§13.277).

Измерено: юнит 117 орошал, на следующем ходу получал `cancel_order` запасным ходом
(предпочтение 0.000, отмена обратима) — и орошение не доводилось до конца:
`turn 4: irrigation`, `turn 5: cancel_order`, `turn 6: irrigation`, `turn 9: cancel_order`.
Вложение ходов уничтожалось, щиты не росли.

Правило вывернутое из 13.271/13.276: простой не смеет обойти вложение в позицию — значит
уничтожение вложения не смеет обойти простой. Цена отмены не ноль, а минус: ноль выглядел
бы как «эффекта нет» и позволял выбирать отмену снова.

Надбавку простою НЕ даём: тогда простой обошёл бы `goto` и `fortify`, и агент перестал бы
ходить. Штраф получает только отмена. Идемпотентно.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "brain" / "generator" / "heuristics.py"

CONST_ANCHOR = "TILE_WORK_ACTIONS = ('mine', 'irrigation', 'road', 'railroad', 'plant', 'cultivate')\n"
CONST_NEW = CONST_ANCHOR + '''
#: Отмена собственного приказа. Стоит НЕ ноль, а минус (§13.277): отмена уничтожает уже
#: вложенные ходы. Измерено — юнит орошал, на следующем ходу получал `cancel_order`
#: запасным ходом, и орошение не доводилось до конца (`turn 4: irrigation`,
#: `turn 5: cancel_order`, `turn 6: irrigation`, `turn 9: cancel_order`).
CANCEL_ORDER_ACTIONS = ('cancel_order',)
'''

EDIT_OLD = """        elif any(w in name for w in TILE_WORK_ACTIONS):
            score += 1.0
        return score
"""
EDIT_NEW = """        elif any(w in name for w in TILE_WORK_ACTIONS):
            score += 1.0
        elif any(c in name for c in CANCEL_ORDER_ACTIONS):
            # Отмена уничтожает вложенные ходы: её цена — минус, а не ноль. Иначе она
            # выигрывает запасной ход у простого (простой обратим, отмена тоже) и
            # вложение гибнет — измерено: орошение не доводилось до конца.
            score -= 1.0
        return score
"""

text = PATH.read_text(encoding="utf-8")
changed = 0
for old, new in ((CONST_ANCHOR, CONST_NEW), (EDIT_OLD, EDIT_NEW)):
    if new in text:
        print("уже внесено")
        continue
    assert text.count(old) == 1, f"якорь не однозначен: {old[:60]!r}"
    text = text.replace(old, new)
    changed += 1

PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {changed}")

import ast  # noqa: E402
ast.parse(text)
print("синтаксис ок")
