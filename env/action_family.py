"""Семейство действия: имя без параметров.

Живёт отдельным модулем, потому что это определение нужно и модели мира, и
учёту заклинивших действий, а импортировать `env.experiments` из обоих мест
нельзя — вышел бы цикл.

Правило одно и оно неочевидно, поэтому продублировано здесь только один раз:
**снимается весь числовой хвост**, а не всё после первого `_` и не один токен.
Иначе `buy_improvement` превратился бы в `buy`; `set_sci_lux_tax_0_40_60` — в
`set`; а `city_work_13_-2_-1` и `city_work_9_-2_0` остались бы разными
семействами (так и было: живой прогон показал, что из-за этого бюджет
любопытства по семейству никогда не исчерпывался).
"""
from __future__ import annotations


def is_number(token: str) -> bool:
    """Числовой параметр действия: `40`, `-2`, `0` (координаты бывают отрицательными)."""
    text = token.lstrip("-")
    return bool(text) and text.isdigit()


def family_of(action_name: str) -> str:
    """`set_sci_lux_tax_0_40_60` → `set_sci_lux_tax`; `city_work_13_-2_-1` → `city_work`."""
    tokens = str(action_name or "").split("_")
    while len(tokens) > 1 and is_number(tokens[-1]):
        tokens.pop()
    return "_".join(tokens)
