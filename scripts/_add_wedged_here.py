"""`is_wedged_here` — падало ли ИМЕННО ЗДЕСЬ, без устаревших семейных отказов (§13.275).

Почему не `is_wedged(context=...)`: тот складывает `global_active` (устаревшие отказы без
координат) и `local_active`, поэтому `unit/build_city` — 3 отказа и 37 успехов — резался в
НОВЫХ клетках. Измерено: 176 исключений за прогон, обе руки отыграли 20 ходов со счётом 0.0.

Правка идемпотентна.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "env" / "wedged.py"

ANCHOR = "def is_wedged_family(ctrl_type: str, action_name: str) -> bool:\n"

NEW_FUNC = '''def is_wedged_here(ctrl_type: str, action_name: str, position) -> bool:
    """Падало ли действие ИМЕННО В ЭТОЙ клетке (§13.275).

    Отдельно от `is_wedged(context=...)`, потому что тот складывает `global_active`
    (устаревшие отказы без координат) с `local_active`. Измерено: `unit/build_city` — 3
    отказа и 37 успехов — резался им в НОВЫХ клетках, 176 исключений за прогон, обе руки
    получили счёт 0.0. Здесь спрашивается только своя клетка: исправное действие режем
    лишь там, где оно уже падало.
    """
    if not ctrl_type or not action_name or position is None:
        return False
    entry = load_wedged().get(key_of(ctrl_type, action_name))
    if not entry:
        return False
    try:
        key = _scope_key((int(position[0]), int(position[1])))
    except (TypeError, ValueError, IndexError, KeyError):
        return False
    scope = (entry.get("scopes") or {}).get(key)
    if not scope:
        return False
    return _active_failures(str(scope.get("reason", "timeout")),
                            int(scope.get("seen", 0)),
                            int(scope.get("resolved_seen", 0)))


'''

text = PATH.read_text(encoding="utf-8")
if "def is_wedged_here(" in text:
    print("функция уже есть")
else:
    assert text.count(ANCHOR) == 1, "якорь не однозначен"
    text = text.replace(ANCHOR, NEW_FUNC + ANCHOR)
    PATH.write_text(text, encoding="utf-8")
    print("функция добавлена")

import ast  # noqa: E402
ast.parse(text)
print("синтаксис ок")
