"""Стратегия без действия основания не может основать город — и меряет список, не игру."""
from __future__ import annotations

from brain.generator.heuristics import ALL_STRATEGIES, HeuristicGenerator

#: Действия, которыми стратегия основывает город. Оба имени в ходу: агент синтезирует
#: `build_city`, а спецификация роли зовёт его `found_city`.
FOUNDING_ACTIONS = ("build_city", "found_city")

#: Простой. Обратим, поэтому в паритете он обходил основание (§13.270).
IDLE_ACTION = "keep_activity"


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
    for strategy in ALL_STRATEGIES:
        gen = HeuristicGenerator(strategy=strategy)
        cand = {"action_name": "build_city", "ctrl_type": "unit"}
        assert gen._preference_score(cand) > 0.0, (
            f"{strategy.name}: `build_city` оценён нулём — город не будет основан")


def test_founding_outranks_idling_for_every_strategy():
    """СТРОГО выше простоя, а не в паритете.

    Измерено на живой серии (слот 6300, 15 ходов, `--no-dof`): после того как основание
    попало в списки всех рук, города всё равно не основывались — юнит-поселенец ходил
    `keep_activity`. Причина: набор действий сравнивается как
    `max(предпочтение, ΔDoF, обратимость)`, основание и простой давали РАВНОЕ
    предпочтение (по одному совпадению), а по обратимости простой выигрывал — основание
    необратимо. Основание города не может проигрывать простому ходу.
    """
    idle = {"action_name": IDLE_ACTION, "ctrl_type": "unit"}
    found = {"action_name": "build_city", "ctrl_type": "unit"}
    for strategy in ALL_STRATEGIES:
        gen = HeuristicGenerator(strategy=strategy)
        s_found, s_idle = gen._preference_score(found), gen._preference_score(idle)
        assert s_found > s_idle, (
            f"{strategy.name}: основание {s_found} не выше простоя {s_idle} — "
            f"поселенец будет простаивать, а не основывать")
