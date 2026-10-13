"""Применить правило клина на ПУТИ ЮНИТОВ (§13.274).

Формула (рекомендованная):

    запрет = is_wedged_family(ctrl, имя)                   # отказов >= 2 и успехов ноль
             или is_wedged(ctrl, имя, context=позиция)      # либо эта клетка уже падала

Семейно режем только безнадёжное (ни разу не удалось), исправное — лишь там, где оно уже
клинило. Проверено на живом реестре: `plant` позиционно не режется (каждая из 25 клеток
падала однажды), поэтому без семейного условия рука залипает каждый матч; `build_city`
(3 отказа, 37 успехов) семейным условием не трогается — иначе гибнет основание города.

Правка идемпотентна.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

IMPORT_OLD = "from env.wedged import record_success, record_wedged\n"
IMPORT_NEW = ("from env.wedged import is_wedged, is_wedged_family, record_success, "
              "record_wedged\n")

HELPER = '''def _is_action_wedged(ctrl: str, name: str, position) -> bool:
    """Заклинивало ли уже это действие — по правилу §13.274.

    Семейно режем БЕЗНАДЁЖНОЕ (отказов >= 2 и ни одного успеха), исправное — только в той
    клетке, где оно уже падало. Измерено на живом реестре: `unit/plant` — 26 отказов,
    0 успехов (резать), `unit/build_city` — 3 отказа, 37 успехов (играть; семейный запрет
    убил бы основание города).
    """
    try:
        if is_wedged_family(ctrl, name):
            return True
    except Exception:  # noqa: BLE001
        return False
    if position is None:
        return False
    try:
        return bool(is_wedged(ctrl, name, context={"position": list(position)}))
    except Exception:  # noqa: BLE001
        return False


def _drop_wedged_candidates(cands: list, dof_state) -> list:
    """Выкинуть кандидатов, о которых известно, что стенд на них заклинивает.

    Живьём экономическая рука залипала на втором ходу в КАЖДОЙ партии (`unit/plant`),
    потому что путь юнитов реестр не спрашивал вовсе: сыграно 1 ход из 20, счёт 0.7
    против 5.7 у экспансиониста.
    """
    positions = getattr(dof_state, "positions", None) or {}
    out = []
    for c in cands:
        act = _to_action(c)
        if not act:
            out.append(c)
            continue
        ctrl = str(act[0])
        actor = str(act[1]) if len(act) >= 2 else ""
        name = str(act[2]) if len(act) >= 3 else ""
        position = positions.get(actor) or positions.get(f"{ctrl}_{actor}")
        if _is_action_wedged(ctrl, name, position):
            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                print(f"  [клин] {ctrl}/{name} — известно, что заклинивает; исключено",
                      flush=True)
            continue
        out.append(c)
    return out


'''

CALL_OLD = '''                    descore = _apply_common_rules(
                        gen.generate_candidates(dof.state, avail), obs, extractor,
                        env_getter, avail)
'''
CALL_NEW = '''                    descore = _apply_common_rules(
                        gen.generate_candidates(dof.state, avail), obs, extractor,
                        env_getter, avail)
                    # §13.274: клин — ИЗМЕРЕННЫЙ факт, и он обязан отсекать действие
                    # ЛЮБОГО рода. Без этого `unit/plant` ставился снова и залипал.
                    descore = _drop_wedged_candidates(descore, dof.state)
'''

text = PATH.read_text(encoding="utf-8")
changed = 0

if IMPORT_NEW in text:
    print("импорт уже есть")
else:
    assert text.count(IMPORT_OLD) == 1, "якорь импорта не однозначен"
    text = text.replace(IMPORT_OLD, IMPORT_NEW)
    changed += 1

if "def _drop_wedged_candidates(" in text:
    print("функции уже есть")
else:
    anchor = "def _apply_common_rules(cands: list, obs: dict, extractor, env_getter,\n"
    assert text.count(anchor) == 1, "якорь _apply_common_rules не однозначен"
    text = text.replace(anchor, HELPER + anchor)
    changed += 1

if "_drop_wedged_candidates(descore, dof.state)" in text:
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
