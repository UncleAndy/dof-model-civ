"""Стратегия без действия основания не может основать город — и меряет список, не игру."""
from __future__ import annotations

from brain.generator.heuristics import ALL_STRATEGIES

#: Действия, которыми стратегия основывает город. Оба имени в ходу: агент синтезирует
#: `build_city`, а спецификация роли зовёт его `found_city`.
FOUNDING_ACTIONS = ("build_city", "found_city")


def test_every_strategy_can_found_a_city():
    """Основание — решение ИГРЫ, а не доменная склонность: без него рука не играет.

    Измерено на серии `--no-dof` (порт 6319, 30 ходов): четыре руки из пяти делали
    `keep_activity` каждый ход и не основали ни одного города — счёт 0 против 7 у
    случайной политики. Причина в списке предпочтений: у них нет действия основания,
    а выбор без DoF идёт ровно предпочтением (`_preference_score`). Такая рука меряет
    список, а не игру, и сравнение с встроенным ИИ по ней невозможно.
    """
    missing = [s.name for s in ALL_STRATEGIES
               if not any(f in s.preferred_unit_actions for f in FOUNDING_ACTIONS)]
    assert not missing, f"стратегии без действия основания: {missing}"


def test_preference_score_rewards_founding_for_every_strategy():
    """Проверка на живом пути оценки, а не на составе списка: кандидат `build_city`
    обязан получать ненулевое предпочтение у КАЖДОЙ стратегии."""
    from brain.generator.heuristics import HeuristicGenerator
    for strategy in ALL_STRATEGIES:
        gen = HeuristicGenerator(strategy=strategy)
        cand = {"action_name": "build_city", "ctrl_type": "unit"}
        assert gen._preference_score(cand) > 0.0, (
            f"{strategy.name}: `build_city` оценён нулём — город не будет основан")
