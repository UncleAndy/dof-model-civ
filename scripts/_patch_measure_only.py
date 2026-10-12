"""Дать замерщику выбор работы (`--only irrigation` / `--only mine`) и свободный бюджет.

Повод: `pick_work` предпочитает дороги, поэтому замер всегда мерил дорогу, а нам нужно разрешить
расхождение «ирригация: правила мира +1 пища, прежний наш замер 0» (§13.257).
"""
from __future__ import annotations

import pathlib

P = pathlib.Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/measure_terrain_effect.py")
src = P.read_text(encoding="utf-8")

OLD_ARG = '''    p.add_argument("--turns", type=int, default=12)'''
NEW_ARG = '''    p.add_argument("--turns", type=int, default=12)
    #: Замер одной работы: `--only irrigation` / `--only mine` / `--only road`.
    #: Без него берётся первая доступная (в порядке предпочтения — дороги).
    p.add_argument("--only", default=None)'''
assert OLD_ARG in src, "место аргумента --turns не найдено"
src = src.replace(OLD_ARG, NEW_ARG, 1)

OLD_SIG = '''def pick_work(actions: dict) -> tuple[str, object] | None:
    """Лучшая валидная работа на клетке: сначала те, что ставят экстру."""
    for group in WORK_PREFERENCE:
        for name, params in actions.items():
            if params and any(name.startswith(p) for p in group):
                return name, params
    return None'''
NEW_SIG = '''def pick_work(actions: dict, only: str | None = None) -> tuple[str, object] | None:
    """Лучшая валидная работа на клетке: сначала те, что ставят экстру.

    `only` сужает выбор до одной работы (`irrigation`, `mine`, `road`, …) — иначе замер
    всегда брал бы дорогу, и вопрос «даёт ли ирригация пищу» остался бы незакрытым.
    """
    if only:
        for name, params in actions.items():
            if params and name.startswith(only):
                return name, params
        return None
    for group in WORK_PREFERENCE:
        for name, params in actions.items():
            if params and any(name.startswith(p) for p in group):
                return name, params
    return None'''
assert OLD_SIG in src, "функция pick_work не найдена в ожидаемом виде"
src = src.replace(OLD_SIG, NEW_SIG, 1)

OLD_CALL = '''                choice = pick_work(actions)'''
NEW_CALL = '''                choice = pick_work(actions, args.only)'''
assert OLD_CALL in src, "место вызова pick_work не найдено"
src = src.replace(OLD_CALL, NEW_CALL, 1)

OLD_BUDGET = '''    signal.alarm(560)'''
NEW_BUDGET = '''    #: Бюджет матча: по умолчанию 560 с, но замер одной работы требует времени —
    #: работа идёт 3-4 хода, и матч надо довести до её конца.
    signal.alarm(int(os.environ.get("TERRAIN_MEASURE_BUDGET", "560")))'''
assert OLD_BUDGET in src, "место бюджета не найдено"
src = src.replace(OLD_BUDGET, NEW_BUDGET, 1)

P.write_text(src, encoding="utf-8")
print("замерщик: добавлен --only, бюджет управляется TERRAIN_MEASURE_BUDGET")
