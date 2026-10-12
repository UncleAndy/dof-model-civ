"""Сторож на удержание постановки: молчание при пустом `held` пропускало соперника.

Пойманная ошибка (§13.229, след отправок основного пути): удержание (§13.196) убирало
соперников только если в списке ЕСТЬ кандидат на текущий предмет:

    held = [c for c in out if c[0] == current_name]
    if held:
        out = held

Если кандидата на текущий предмет в списке нет (обычный случай — генератор не
предлагает то, что уже строится), `held` пуст, ветка МОЛЧИТ, и соперник проходит
насквозь. В живой партии это давало ровное чередование постановки в КАЖДОМ городе:
19 `produce_Barracks` и 18 `produce_Settlers` за 20 ходов, ни один предмет не
достраивался — поселенцы не выходили, городов 2 против 5 у встроенного ИИ.

Путь живого матча в тестах не исполняется (дорог — стоит партии), поэтому проверка
статическая: разбираем исходник и требуем, чтобы у ветки удержания была ветвь «иначе»,
которая НЕ оставляет соперников вовсе.
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIVE = ROOT / "brain" / "forecast" / "live.py"


def _productions_guard() -> bool:
    """Есть ли `else`, который при пустом `held` гасит производственных кандидатов."""
    tree = ast.parse(LIVE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "productions"):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.If):
                continue
            test = inner.test
            if not (isinstance(test, ast.Name) and test.id == "held"):
                continue
            # Ветвь `else` самого удержания обязана быть `elif <условие про out>`,
            # внутри которого список ГАСИТСЯ. Проверено откатом: с `elif False:` (и с
            # любым другим условием) сторож обязан падать, поэтому условие читается,
            # а не просто «где-то рядом есть `out = []`».
            for branch in inner.orelse:
                if not (isinstance(branch, ast.If)
                        and isinstance(branch.test, ast.Name)
                        and branch.test.id == "out"):
                    continue
                for sub in ast.walk(branch):
                    if (isinstance(sub, ast.Assign)
                            and getattr(sub.value, "elts", None) == []
                            and any(isinstance(t, ast.Name) and t.id == "out"
                                    for t in sub.targets)):
                        return True
    return False


def test_hold_does_not_stay_silent_when_no_candidate_for_current_item():
    """Удержание обязано ГАСИТЬ список, а не молчать (иначе город меняет постановку каждый ход)."""
    assert _productions_guard(), (
        "удержание постановки (§13.196) снова молчит, когда кандидата на текущий предмет "
        "в списке нет: соперник пройдёт, и город начнёт чередовать постановку каждый ход "
        "(измерено §13.229). Нужна ветвь `elif out: ... out = []`."
    )