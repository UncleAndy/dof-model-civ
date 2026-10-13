"""Перенос `city_tile_value` строка в строку (§13.284).

Источник: `server/advisors/infracache.c:293` закреплённого коммита
`14b7a645a74155d4f3dd300221c5b4f0ffca8fe8` (локально:
`drafts/reference/freeciv-src/server/advisors/infracache.c`). Веса — `advbuilding.h:19-21`
(30/17/18), у нас они уже есть в `env/config.py:380-382` и совпадают до цифры.

Идемпотентно.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "brain" / "ai_default" / "values.py"

FUNC = '''

#: Веса выходов клетки — `server/advisors/advbuilding.h:19-21`, у нас `env/config.py:380-382`.
TILE_FOOD_WEIGHTING: float = 30.0
TILE_SHIELD_WEIGHTING: float = 17.0
TILE_TRADE_WEIGHTING: float = 18.0


def city_tile_value(food: float, shield: float, trade: float, *,
                    food_weighting: float = TILE_FOOD_WEIGHTING,
                    shield_weighting: float = TILE_SHIELD_WEIGHTING,
                    trade_weighting: float = TILE_TRADE_WEIGHTING) -> float:
    """`city_tile_value` из `server/advisors/infracache.c:293` — строка в строку.

    «Мера добротности клетки для города». Каждая статья весит своим весом, и ПОЛОВИНА
    веса добавляется, если статья ненулевая: по комментарию исходника это даёт ровный
    баланс клеток и учитывает эффекты `INC_TILE`.

    FIXME исходника сохранён как факт: его `foodneed` и `prodneed` всегда 0
    («FIXME: foodneed and prodneed are always 0»), поэтому аргументов под них нет — иначе
    мы повторяли бы несуществующее поведение.

    Нужна для выбора работы рабочим: `settler_evaluate_improvements`
    (`server/advisors/autoworkers.c:530`) считает `oldv = city_tile_value(pcity, ptile, 0, 0)`
    и сравнивает с ценностью клетки ПОСЛЕ работы.
    """
    value = food * food_weighting
    if food > 0:
        value += food_weighting / 2
    value += shield * shield_weighting
    if shield > 0:
        value += shield_weighting / 2
    value += trade * trade_weighting
    if trade > 0:
        value += trade_weighting / 2
    return value
'''

text = PATH.read_text(encoding="utf-8")
if "def city_tile_value(" in text:
    print("уже перенесено")
else:
    PATH.write_text(text.rstrip() + FUNC, encoding="utf-8")
    print("city_tile_value перенесён")

import ast  # noqa: E402
ast.parse(PATH.read_text(encoding="utf-8"))
print("синтаксис ок")
