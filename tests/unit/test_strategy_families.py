"""Каждая рука обязана быть способна ИГРАТЬ — рода решений не выпадают (§13.275).

При `--no-dof` выбор идёт ровно `_preference_score`, то есть СЧЁТОМ совпадений со списком
(порядок внутри списка не значит ничего). Веса стратегий (`domain_weights`) умножают
DoF-выигрыш, а он в этом режиме выключен и равен нулю — значит список работает не
склонностью, а РАЗРЕШЕНИЕМ.

Измерено (серия 3x3 по 20 ходов, `--no-dof`): `expansionist` — счёт 5.7 и 2 города,
`defensive` — счёт 1.0 и 1 город, обе отыграли полные 20 ходов без ошибок. У оборонительной
в списке нет НИ ОДНОЙ работы клетки и ни одного `goto` — она не может ни улучшить клетку,
ни куда-то пойти.

Рода, обязательные у КАЖДОЙ руки, — это решения ИГРЫ, а не доменная склонность: основание
города, работа клетки, ход/раскрытие тумана. Набор работ берётся ПОЛНЫЙ: что доступно,
решает местность, а не наша догадка. Свои склонности остаются СВЕРХ базы.
"""
from __future__ import annotations

from brain.generator.heuristics import ALL_STRATEGIES

#: род → хотя бы одно из действий обязано быть в списке руки
GAME_FAMILIES: dict[str, tuple[str, ...]] = {
    "основание города": ("build_city", "found_city"),
    "работа клетки": ("road", "railroad", "mine", "irrigation", "plant", "cultivate"),
    "ход и раскрытие тумана": ("goto",),
}

#: Полный набор работ клетки из базы.
TILE_WORK_BASE = ("road", "railroad", "mine", "irrigation", "plant", "cultivate")

#: Что было в списках ДО внесения базы — сверяем, что ничего не потеряно.
PRIOR_UNIT_ACTIONS: dict[str, tuple[str, ...]] = {
    "defensive": ("build_city", "found_city", "fortify", "fortress", "sentry",
                  "keep_activity"),
    "expansionist": ("build_city", "found_city", "road", "railroad", "goto", "irrigation"),
    "economic": ("build_city", "found_city", "road", "railroad", "mine", "plant",
                 "cultivate", "goto"),
    "technological": ("build_city", "found_city", "keep_activity", "fortify", "sentry"),
    "diplomatic": ("build_city", "found_city", "keep_activity", "fortify", "sentry"),
}


def test_every_arm_can_play_every_game_family():
    gaps: list[str] = []
    for strategy in ALL_STRATEGIES:
        for family, actions in GAME_FAMILIES.items():
            if not any(a in strategy.preferred_unit_actions for a in actions):
                gaps.append(f"{strategy.name}: нет рода «{family}»")
    assert not gaps, "рука структурно не способна играть: " + "; ".join(gaps)


def test_every_arm_has_the_full_tile_work_set():
    """Не «какая-то одна работа», а весь набор: доступное решает местность, не догадка."""
    gaps = [s.name for s in ALL_STRATEGIES
            if not all(a in s.preferred_unit_actions for a in TILE_WORK_BASE)]
    assert not gaps, f"у рук нет полного набора работ клетки: {gaps}"


def test_nothing_was_taken_away_from_any_arm():
    """Правка ТОЛЬКО добавляет: склонности рук сохраняются, иначе меряется другая политика."""
    by_name = {s.name: s for s in ALL_STRATEGIES}
    lost: list[str] = []
    for name, prior in PRIOR_UNIT_ACTIONS.items():
        now = by_name[name].preferred_unit_actions
        gone = [a for a in prior if a not in now]
        if gone:
            lost.append(f"{name}: потеряно {gone}")
    assert not lost, "; ".join(lost)


def test_a_distinctive_preference_survives_on_top_of_the_base():
    """Склонность остаётся СВЕРХ базы: оборона у оборонительной никуда не уходит."""
    by_name = {s.name: s for s in ALL_STRATEGIES}
    assert "fortify" in by_name["defensive"].preferred_unit_actions
    assert "sentry" in by_name["defensive"].preferred_unit_actions
