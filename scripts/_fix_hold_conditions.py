"""Условия удержания — по замеру, а не по первому предположению (§13.281).

Измерено на живом прогоне (`/tmp/dof_actdiag.log`): занятие юнита ПРИХОДИТ (значения 0, 13, 15
— простой, дорога, посадка), но `keep_activity` у занятых юнитов в предложении НЕТ. Мой
предохранитель «применяем только если предложен keep_activity» из-за этого глушил правило, и
чередование продолжалось.

Новые условия, оба измеряемые:

1. Занятому юниту не выдаём другой приказ (основание города и `keep_activity` разрешены).
2. Если после этого у стороны не осталось НИ ОДНОГО хода — возвращаем исходное: сторона без
   хода хуже смены приказа.

Идемпотентно.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

CHUNK_A_OLD = '''    # Кто вообще может «продолжить»: без такого предложения правило молчит — юнит без хода
    # хуже, чем юнит со сменённым приказом.
    resumable: set = set()
    for c in cands:
        act = _to_action(c)
        if act and str(act[0]) == "unit" and str(act[2]) == "keep_activity":
            resumable.add(str(act[1]))
    if not resumable:
        return cands

'''
CHUNK_A_NEW = ''

CHUNK_B_OLD = '''        if ctrl != "unit" or actor not in resumable:
            out.append(c)
            continue
'''
CHUNK_B_NEW = '''        if ctrl != "unit":
            out.append(c)
            continue
'''

CHUNK_C_OLD = '''                  f"отложено — смена приказа уничтожила бы вложенные ходы", flush=True)
    return out
'''
CHUNK_C_NEW = '''                  f"отложено — смена приказа уничтожила бы вложенные ходы", flush=True)
    if not out:
        # Сторона без хода хуже смены приказа: правило уступает, а не оставляет сторону
        # без решения (измерено: занятых юнитов 3–5 за ход, и у них нет keep_activity).
        return cands
    return out
'''

DOC_OLD = '''    Основание города разрешено: оно решение ИГРЫ и стоит ВЫШЕ работы клетки (§13.271/13.276),
    поэтому занятый поселенец обязан мочь основать город вместо дороги.
    """
'''
DOC_NEW = '''    Основание города разрешено: оно решение ИГРЫ и стоит ВЫШЕ работы клетки (§13.271/13.276),
    поэтому занятый поселенец обязан мочь основать город вместо дороги.

    Измерено после первой версии: занятие ПРИХОДИТ (0, 13, 15), а `keep_activity` у занятых
    юнитов в предложении НЕТ — предохранитель «нужен keep_activity» глушил правило, и
    чередование продолжалось. Поэтому правило применяется без этого условия, но уступает,
    если оставляет сторону без хода.
    """
'''

text = PATH.read_text(encoding="utf-8")
changed = 0
for old, new in ((CHUNK_A_OLD, CHUNK_A_NEW), (CHUNK_B_OLD, CHUNK_B_NEW),
                 (CHUNK_C_OLD, CHUNK_C_NEW), (DOC_OLD, DOC_NEW)):
    if new and new in text:
        print("уже внесено")
        continue
    if not new and old not in text:
        print("уже внесено (блок удалён)")
        continue
    assert text.count(old) == 1, f"якорь не однозначен: {old[:50]!r}"
    text = text.replace(old, new)
    changed += 1

PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {changed}")

import ast  # noqa: E402
ast.parse(text)
print("синтаксис ок")
