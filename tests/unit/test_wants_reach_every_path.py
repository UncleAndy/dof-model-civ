"""Правило о роде действий обязано жить в ТОЙ функции, которую вызывает каждый путь.

Измерено (§13.273): желание поселенца было внесено в `productions()`, но общий путь
(без DoF) берёт цену через `type_price` (`live.py`: `type_price_of=type_price`).
Поэтому желание не спрашивалось ВООБЩЕ — за 12 ходов в следе не было ни одной строки
`[желание]`, город остался единственным, а ошибка выглядела как «эффекта нет».

Проверка нарочно СТРУКТУРНАЯ: дефект был не в числах, а в том, что правило стояло в
функции, до которой путь не доходит. Поведенческий тест такое пропускает, если обе
функции формально работают.
"""
from __future__ import annotations

import inspect
import re

from brain.forecast import live

#: Функция цены, которую общий путь (без DoF) получает как `ctx.type_price_of`.
PATH_FUNCTION = "type_price"
#: Желания, которые обязаны спрашиваться в этой функции.
WANTS = ("worker_want", "founder_want")


def _body_of(source: str, name: str) -> str:
    """Тело вложенной функции `name` из исходника — до следующей вложенной `def`."""
    start = source.index(f"    def {name}(")
    after = source[start + 1:]
    nxt = re.search(r"\n    def \w+\(", after)
    return after[:nxt.start()] if nxt else after


def test_the_no_dof_path_asks_the_wants():
    source = inspect.getsource(live.build_context)
    body = _body_of(source, PATH_FUNCTION)
    missing = [w for w in WANTS if w not in body]
    assert not missing, (
        f"`{PATH_FUNCTION}` (цена типа, её же получает общий путь без DoF) не спрашивает "
        f"{missing} — правило стоит в функции, до которой путь не доходит")
