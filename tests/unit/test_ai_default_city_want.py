"""Сторож отображения ЗАПИСИ ГОРОДА в ценность его города (`effects.city_want`).

Формула проверяется в своём стороже (`test_ai_default_effects.py`); здесь — ровно то, чего там
нет: сопоставление полей записи мира с её входами. Числа посчитаны рукой по его строкам:
`daicity.c:1421` `prod[O_GOLD] -= upkeep` ДО взвешивания, и веса `advdata.c:499-508`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brain.ai_default.city_want import building_want_now  # noqa: E402
from brain.ai_default.effects import city_want as his_city_want  # noqa: E402


def test_does_not_define_a_second_formula():
    """Формула одна: наш модуль обязан ЗВАТЬ его функцию, а не переписывать её.

    Это сторож против дубля — при заходе дубль уже был написан мной же и пойман проверкой.
    """
    import brain.ai_default.city_want as mod
    assert getattr(mod, "city_want", None) is his_city_want
    assert not hasattr(mod, "priorities"), "приоритеты — в effects, второй копии быть не должно"


def test_record_maps_to_his_inputs():
    """рука: еда 4×30 + щиты 3×17 + наука 6×21.6 + золото (2−1)×18 = 120+51+129.6+18 = 318.6."""
    rec = {"prod_food": 4, "prod_shield": 3, "science": 6, "luxury": 0, "gold": 2, "upkeep": 1}
    value, report = building_want_now(rec)
    assert value is not None
    assert abs(value - (120.0 + 51.0 + 6.0 * 21.6 + 18.0)) < 1e-9
    assert "НЕТ" not in report, "разделение торговли было — жаловаться не на что"


def test_upkeep_is_subtracted_from_gold_before_weighting():
    """Его строка `prod[O_GOLD] -= upkeep`: золото 2 при содержании 1 весит как 1, не как 2."""
    base = {"prod_food": 0, "prod_shield": 0, "science": 0, "luxury": 0}
    with_up = building_want_now({**base, "gold": 2, "upkeep": 1})[0]
    without = building_want_now({**base, "gold": 1, "upkeep": 0})[0]
    assert abs(with_up - without) < 1e-9


def test_missing_trade_split_is_said_out_loud_not_silently_zero():
    """Нет разделения торговли — отчёт говорит прямо, а не подставляет нули молча."""
    value, report = building_want_now({"prod_food": 4, "prod_shield": 3, "upkeep": 1})
    assert value is not None
    assert "НЕТ" in report and "торговля не учтена" in report


def test_missing_outputs_refuse_with_a_reason():
    """Нет выходов — отказ с причиной: молчание обязано отличаться от нуля."""
    value, report = building_want_now({"size": 2})
    assert value is None
    assert "нет выходов" in report


def test_not_a_record_refuses_with_a_reason():
    assert building_want_now(None)[0] is None
