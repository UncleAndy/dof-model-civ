"""Сторож на порог основания города: берём ЧИСЛО ВСТРОЕННОГО ИИ, а не своё.

Указание владельца (2026-10-12): «Согласовывай такие пороги с реализацией внутреннего ИИ.
Используй значения из него.» Замер, который к этому привёл (§13.204): с нашим порогом
«6.0 еды с убыванием 0.4/ход» агент не основал НИ ОДНОГО города за 40 ходов — на той же
карте, где встроенный ИИ основал 1–2 города за ТРИ хода (канал стенда, место 0 — нули
по всем категориям, §13.204).

Его правило (`ai/default/daisettler.c`):

* `:826` — площадка берётся при `cr->result > 0` (порог основания);
* `:816` — `cr->result = amortize(cr->total, PERFECTION * turns)`, `PERFECTION = 3` (`:104`);
* `:823` — из результата вычтен ценник самого поселенца;
* `:94/:846` — `RESULT_IS_ENOUGH = 250` это «хватит искать дальше», НЕ порог основания;
* `:98/:362` — `GROWTH_PRIORITY = 15`; `:109` — `GROWTH_POTENTIAL_DEEMPHASIS = 8`.

Порог голода его собственный (`food_starvation`/`shield_starvation`) уже стоит в
`env/site_eval.py` — здесь сторож на то, чтобы наши изобретённые числа не возвращались.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

from env.config import (AI_GROWTH_POTENTIAL_DEEMPHASIS, AI_GROWTH_PRIORITY,
                        AI_SITE_FOUNDING_BAR, AI_SITE_PERFECTION,
                        AI_SITE_RESULT_IS_ENOUGH, first_city_food_gate)


def test_the_founding_bar_is_the_built_in_ai_one():
    assert AI_SITE_FOUNDING_BAR == 0.0, "порог основания — `cr->result > 0` (daisettler.c:826)"


def test_the_other_built_in_numbers_are_carried_over():
    assert AI_SITE_RESULT_IS_ENOUGH == 250     # `RESULT_IS_ENOUGH`, daisettler.c:94
    assert AI_SITE_PERFECTION == 3             # `PERFECTION`, daisettler.c:104
    assert AI_GROWTH_PRIORITY == 15            # `GROWTH_PRIORITY`, daisettler.c:98
    assert AI_GROWTH_POTENTIAL_DEEMPHASIS == 8  # daisettler.c:109


def test_the_legacy_decay_exists_but_is_no_longer_the_bar():
    """Прежний закон остаётся в файле как запись замера, но порогом больше не является."""
    assert first_city_food_gate(1) == 6.0        # сохранился исторический расчёт
    assert first_city_food_gate(1) != AI_SITE_FOUNDING_BAR


def test_both_paths_take_the_bar_from_the_built_in_ai():
    live = (ROOT / "brain" / "forecast" / "live.py").read_text(encoding="utf-8")
    ext = (ROOT / "env" / "entity_extractor.py").read_text(encoding="utf-8")
    for text, who in ((live, "прогноз"), (ext, "прежний путь")):
        assert "AI_SITE_FOUNDING_BAR" in text, f"{who}: порог не из встроенного ИИ"
        assert "first_city_food_gate(" not in text, (
            f"{who}: снова берёт НАШ изобретённый порог с убыванием — он запрещал "
            "основание города целиком (§13.204)")