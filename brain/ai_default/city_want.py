"""Ценность города ПО ЗАПИСИ МИРА — сырьё для оценки постройки (`base_want`).

ФОРМУЛА ЗДЕСЬ НЕ ЖИВЁТ. Её порт — `brain/ai_default/effects.py:city_want`
(`dai_city_want`, `ai/default/daicity.c:1421`), и дублировать её нельзя: два места с одной
формулой разойдутся при первой правке. Здесь только то, чего там нет, — **отображение записи
города мира в её входы** и отчёт о том, что именно взято.

Зачем это нужно. Оценка постройки у его ИИ — контрфакт (`base_want`, `daicity.c:1495`): добавить
постройку и посчитать, насколько изменится ценность города; `building_advisor_choose`
(`server/advisors/advbuilding.c:273`) берёт наибольшую среди доступных. У нас постановку
выбирает НАША оценка, хотя веса управляющего уже его. Без этой функции переносить контрфакт
не на что.

ЗАПУСК ЭТОЙ ЧАСТИ ЕЩЁ НЕ ПОДКЛЮЧЁН — вызывающих на живом пути нет, и это записано в журнале
(13.310). Перенос производства делается шагами: отображение → контрфакт поверх
`effects.improvement_value` → подключение и замер серией. Оставлять после себя код «перенёс и
забыл» в проекте запрещено собственным правилом, поэтому следующее состояние обязано быть
либо подключением, либо удалением.

ЧЕГО В ЗАПИСИ НЕТ И ПОЧЕМУ ЭТО ВИДНО. Разделение торговли (наука / роскошь / золото) мир даёт
не во всех записях. Если его нет — три статьи остаются нулевыми, и отчёт говорит это ПРЯМО:
подставить ставки значило бы выдумать неизвестное, а молчаливый ноль от неизвестности
неотличим («незнание ≠ отсутствие возможностей»).
"""

from __future__ import annotations

from brain.ai_default.effects import city_want


def _num(value):
    """Число или None — но НЕ ноль: ноль значил бы «знаю, что ноль»."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def building_want_now(rec: dict, *, upkeep: float | None = None, tax_rate: float | None = None,
                      wants_science: bool = True):
    """`(ценность города, отчёт)` по записи мира, либо `(None, причина)`.

    Содержание построек вычитается из ЗОЛОТА до взвешивания — его строка
    `prod[O_GOLD] -= city_improvement_upkeep`. Если бы мы вычитали его после взвешивания или
    из общей суммы, постройка с содержанием выглядела бы дешевле, чем она есть.
    """
    if not isinstance(rec, dict):
        return None, "нет записи города"
    food = _num(rec.get("prod_food"))
    shields = _num(rec.get("prod_shield"))
    if food is None or shields is None:
        return None, "в записи города нет выходов еды/щитов — считать нечего"
    up = _num(upkeep) if upkeep is not None else _num(rec.get("upkeep"))
    science = _num(rec.get("science"))
    luxury = _num(rec.get("luxury"))
    gold = _num(rec.get("gold"))
    trade_split_known = science is not None or luxury is not None or gold is not None
    if not trade_split_known:
        science = luxury = gold = 0.0
    gold_net = (gold or 0.0) - (up or 0.0)
    value = city_want(food=food, shields=shields, science=science or 0.0,
                      gold=gold_net, luxury=luxury or 0.0,
                      tax_rate=tax_rate, wants_science=wants_science)
    report = (f"еда {food:g}, щиты {shields:g}, наука {science:g}, роскошь {luxury:g}, "
              f"золото {gold:g} минус содержание {up or 0.0:g}")
    if not trade_split_known:
        report += " — разделения торговли в записи НЕТ, торговля не учтена"
    return value, report
