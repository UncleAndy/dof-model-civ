"""Занятому юниту — продолжать начатое, а не получать другой приказ (§13.281).

Измерено: город не растёт, потому что улучшение клетки не завершается — юнит получает каждый
ход другой приказ (`mine` → `build_road` → `mine`), и каждый новый приказ отменяет
предыдущий. Клетка остаётся базовой, `prod_food` = 2, излишек еды 0, город навсегда на
размере 1: 1 город и население 1 против 23 и 182 у встроенного ИИ.

Мир сам сообщает занятие юнита (`unit_ctrl.units[id]['activity']`, `ACTIVITY_IDLE = 0`
в `version/v14.py:50`), и клиент сам различает занятого (`unit_actions.py:514`) — берём это
из мира, а не догадываемся.

Правило: занятому юниту разрешены ТОЛЬКО `keep_activity` (продолжить начатое) и основание
города (решение ИГРЫ, оно ВЫШЕ работы клетки — §13.271/13.276). Смена рода работы
запрещена. Если продолжения в предложении нет, правило МОЛЧИТ — иначе сторона осталась бы
без хода, а это хуже смены приказа. Города правило не трогает.

Идемпотентно.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

HELPER = '''def _is_idle_activity(value) -> bool:
    """Свободен ли юнит. `ACTIVITY_IDLE = 0` — из кода мира (`version/v14.py:50`).

    Неизвестное значение считаем простым: молчание правила безопаснее, чем запрет вслепую —
    иначе агент перестанет ходить.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return "IDLE" in value.upper()
    try:
        return int(value) == 0
    except (TypeError, ValueError):
        return True


def _unit_activities(env_getter) -> dict:
    """Занятие наших юнитов — из мира (`unit_ctrl.units[id]['activity']`).

    Мир сообщает его сам, и клиент сам различает занятого (`unit_actions.py:514`), поэтому
    это запись мира, а не догадка (решение владельца: код мира — тоже наблюдение).
    """
    if env_getter is None:
        return {}
    try:
        env = env_getter()
        ctl = getattr(getattr(env, "unwrapped", None), "civ_controller", None)
        units = getattr(getattr(ctl, "unit_ctrl", None), "units", None) or {}
        my_id = getattr(ctl, "my_player_id", None)
        out: dict = {}
        for uid, unit in (units.items() if isinstance(units, dict) else ()):
            if not isinstance(unit, dict) or "activity" not in unit:
                continue
            owner = unit.get("owner")
            if my_id is not None and owner is not None and int(owner) != int(my_id):
                continue
            out[str(uid)] = unit.get("activity")
        return out
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("DOF_TRACE_FILTERS") == "1":
            print(f"  [занят] занятие юнитов не прочитано: {type(exc).__name__}: {exc}",
                  flush=True)
        return {}


def _hold_busy_unit_orders(cands: list, activities=None, env_getter=None) -> list:
    """Занятому юниту — продолжать начатое, а не получать ДРУГОЙ приказ (§13.281).

    Измерено (`/tmp/dof_growth.log`): `unit/114` получал КАЖДЫЙ ход другой приказ
    (`mine` → `build_road` → `mine`), поэтому ни одно улучшение не завершалось, клетка
    оставалась базовой, `prod_food` = 2, излишек еды 0 — и город не рос: 1 город и
    население 1 против 23 и 182 у встроенного ИИ.

    Основание города разрешено: оно решение ИГРЫ и стоит ВЫШЕ работы клетки (§13.271/13.276),
    поэтому занятый поселенец обязан мочь основать город вместо дороги.
    """
    if activities is None:
        activities = _unit_activities(env_getter)
    if not activities:
        return cands

    # Кто вообще может «продолжить»: без такого предложения правило молчит — юнит без хода
    # хуже, чем юнит со сменённым приказом.
    resumable: set = set()
    for c in cands:
        act = _to_action(c)
        if act and str(act[0]) == "unit" and str(act[2]) == "keep_activity":
            resumable.add(str(act[1]))
    if not resumable:
        return cands

    out = []
    for c in cands:
        act = _to_action(c)
        if not act:
            out.append(c)
            continue
        ctrl, actor, name = str(act[0]), str(act[1]), str(act[2])
        if ctrl != "unit" or actor not in resumable:
            out.append(c)
            continue
        if _is_idle_activity(activities.get(actor)):
            out.append(c)
            continue
        if name == "keep_activity" or any(f in name for f in FOUNDING_ACTIONS):
            out.append(c)
            continue
        if os.environ.get("DOF_TRACE_FILTERS") == "1":
            print(f"  [занят] unit/{actor} уже занят ({activities.get(actor)}); {name} "
                  f"отложено — смена приказа уничтожила бы вложенные ходы", flush=True)
    return out


'''

IMPORT_OLD = "from brain.generator.heuristics import ALL_STRATEGIES, DEFENSIVE, HeuristicGenerator\n"
IMPORT_NEW = ("from brain.generator.heuristics import (ALL_STRATEGIES, DEFENSIVE, "
              "FOUNDING_ACTIONS,\n                                       HeuristicGenerator)\n")

CALL_OLD = "                    descore = _drop_wedged_candidates(descore, dof.state)\n"
CALL_NEW = (CALL_OLD +
            "                    # §13.281: занятому юниту — продолжать начатое, а не получать\n"
            "                    # другой приказ. Каждый новый приказ отменял предыдущий, и ни\n"
            "                    # одно улучшение не завершалось: город не рос.\n"
            "                    descore = _hold_busy_unit_orders(descore, env_getter=env_getter)\n")

text = PATH.read_text(encoding="utf-8")
changed = 0

if IMPORT_NEW in text:
    print("импорт уже есть")
elif IMPORT_OLD in text:
    text = text.replace(IMPORT_OLD, IMPORT_NEW)
    changed += 1
else:
    # Инвариант вслепую не подставляем: если импорта нет — сообщаем и не трогаем файл.
    raise SystemExit("ЯКОРЬ ИМПОРТА НЕ НАЙДЕН — файл не тронут")

if "def _hold_busy_unit_orders(" in text:
    print("функция уже есть")
else:
    anchor = "def _drop_wedged_candidates(cands: list, dof_state) -> list:\n"
    assert text.count(anchor) == 1, "якорь _drop_wedged_candidates не однозначен"
    text = text.replace(anchor, HELPER + anchor)
    changed += 1

if "_hold_busy_unit_orders(descore, env_getter=env_getter)" in text:
    print("вызов уже есть")
else:
    assert text.count(CALL_OLD) == 1, "якорь вызова не однозначен"
    text = text.replace(CALL_OLD, CALL_NEW)
    changed += 1

PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {changed}")

import ast  # noqa: E402
ast.parse(text)
print("синтаксис ок")
