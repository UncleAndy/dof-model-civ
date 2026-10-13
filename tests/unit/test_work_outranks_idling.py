"""Работа клетки обязана быть строго выше простоя — как и основание города (§13.276).

Измерено (защитная рука, 20 ходов, `--no-dof`, `/tmp/dof_defstops.log`):

```
[без DoF] отправляю unit/keep_activity  125
[без DoF] отправляю unit/goto_0           7
[без DoF] отправляю unit/build_city       4
работ клетки (mine/irrigation/road/plant/cultivate) — НОЛЬ
```

При этом `plant` стенд предлагал (49 раз в логе — как исключённый клином). Механизм тот же,
что чинился у основания: набор сравнивается как `max(предпочтение, ΔDoF, обратимость)`,
работа и простой дают РАВНОЕ предпочтение (по одному совпадению), а по обратимости простой
выигрывает — работа необратима. В результате город с населением 1–2 не получает ни щитов,
ни еды: любой тип строится десятки ходов (измерено: поселенец 40 ходов, дисконт γ^40
роняет его желание 9.2 до 1.6 и он проигрывает казармам 3.71).

Порядок приоритетов, который эти тесты закрепляют:

    основание города  >  работа клетки  >  простой

Почему основание строго выше работы: иначе поселенец, у которого доступны оба действия,
начнёт строить дорогу вместо города.
"""
from __future__ import annotations

from brain.generator.heuristics import ALL_STRATEGIES, HeuristicGenerator

FOUND = {"action_name": "build_city", "ctrl_type": "unit"}
WORK = {"action_name": "mine", "ctrl_type": "unit"}
IDLE = {"action_name": "keep_activity", "ctrl_type": "unit"}


def test_work_outranks_idling_for_every_arm():
    bad: list[str] = []
    for strategy in ALL_STRATEGIES:
        gen = HeuristicGenerator(strategy=strategy)
        work, idle = gen._preference_score(WORK), gen._preference_score(IDLE)
        if work <= idle:
            bad.append(f"{strategy.name}: работа {work} не выше простоя {idle}")
    assert not bad, "; ".join(bad)


def test_founding_still_outranks_work_for_every_arm():
    """Иначе поселенец начинает строить дорогу вместо города."""
    bad: list[str] = []
    for strategy in ALL_STRATEGIES:
        gen = HeuristicGenerator(strategy=strategy)
        found, work = gen._preference_score(FOUND), gen._preference_score(WORK)
        if found <= work:
            bad.append(f"{strategy.name}: основание {found} не выше работы {work}")
    assert not bad, "; ".join(bad)
