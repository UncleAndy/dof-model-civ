"""Сторож выбора технологии — его `ai_choose_tech` (`ai/default/daitech.c`).

Проверяется ровно то, что отделяет перенос от выдумки: при равенстве побеждает ПЕРВАЯ
встреченная (у него строгое `>`), и при полном отсутствии данных семья остаётся нетронутой —
действовать по незнанию нельзя.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brain.ai_default.tech import (  # noqa: E402
    TECH_WANT_FACTOR,
    best_of,
    keep_best_tech,
    tech_want,
    tech_want_total,
)


def test_factor_is_his():
    """`tech_want = v × 14 / 8` — его коэффициент перевода, не наш."""
    assert abs(TECH_WANT_FACTOR - 14.0 / 8.0) < 1e-12
    assert abs(tech_want(100.0, 108.0) - 8.0 * 14.0 / 8.0) < 1e-12
    assert abs(tech_want_total([(100.0, 108.0), (0.0, 0.0)]) - 14.0) < 1e-12


def test_best_of_takes_the_strongest():
    assert best_of({"Alphabet": 0.0, "Amphibious Warfare": 42.5, "Banking": 7.0}) == "Amphibious Warfare"


def test_best_of_keeps_the_first_on_a_tie():
    """При равенстве — первая по порядку мира; перестановка сделала бы выбор случайным."""
    values = {"Alphabet": 5.0, "Advanced Flight": 5.0, "Banking": 1.0}
    assert best_of(values) == "Alphabet"
    assert best_of(dict(reversed(list(values.items())))) == "Advanced Flight"


def test_best_of_ignores_unknown_and_returns_none_without_data():
    """None и мусор — не ноль: считать их нулём значило бы выдумать оценку."""
    assert best_of({"Alphabet": None, "Banking": 0.0}) == "Banking"
    assert best_of({"Alphabet": None}) is None
    assert best_of({}) is None


def _cands(*names):
    return [{"action_name": n, "ctrl_type": "tech"} for n in names]


def test_keep_best_tech_keeps_only_his_choice():
    cands = _cands("research_tech_Alphabet_", "research_tech_Amphibious Warfare_",
                   "produce_Barracks")
    values = {"research_tech_Alphabet_": 0.0, "research_tech_Amphibious Warfare_": 33.0}
    kept = keep_best_tech(cands, name_of=lambda c: c["action_name"],
                          value_of=lambda c: values.get(c["action_name"]),
                          family_prefix="research_tech_")
    names = [c["action_name"] for c in kept]
    assert "research_tech_Amphibious Warfare_" in names
    assert "research_tech_Alphabet_" not in names
    assert "produce_Barracks" in names, "чужие роды действий трогать нельзя"


def test_keep_best_tech_leaves_everything_when_nothing_is_known():
    """Нет данных ни об одной технологии — семья возвращается нетронутой."""
    cands = _cands("research_tech_Alphabet_", "research_tech_Banking_")
    kept = keep_best_tech(cands, name_of=lambda c: c["action_name"],
                          value_of=lambda c: None, family_prefix="research_tech_")
    assert len(kept) == 2


def test_keep_best_tech_does_not_touch_a_lone_candidate():
    """Одна технология в решении — решать нечего, и правило молчит."""
    cands = _cands("research_tech_Alphabet_")
    kept = keep_best_tech(cands, name_of=lambda c: c["action_name"],
                          value_of=lambda c: 1.0, family_prefix="research_tech_")
    assert len(kept) == 1
