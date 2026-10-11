"""Сторож на связку «довод прогноза объявлен И передан».

Пойманная ошибка: в `baselines/run_real_tournament.py` вызов `_forecast_decide(...)`
получил новый довод (`military_names`), а сама функция его не объявила — раннер падал
на ПЕРВОМ же ходу матча (`TypeError: got an unexpected keyword argument`). Тесты этого
не поймали: путь живого матча в них не исполняется, а он дорогой — прогон стоит партии.

Здесь проверка дешёвая и статическая: читаем исходник и сверяем объявление с вызовом.
Так ошибка ловится тестом, а не потерянным прогоном.
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = ROOT / "baselines" / "run_real_tournament.py"
LIVE = ROOT / "brain" / "forecast" / "live.py"


def _params_of(tree: ast.AST, name: str) -> set[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            args = node.args
            return ({a.arg for a in args.args}
                    | {a.arg for a in args.posonlyargs}
                    | {a.arg for a in args.kwonlyargs})
    raise AssertionError(f"функция {name} не найдена")


def _call_kwargs(tree: ast.AST, func_name: str) -> list[set[str]]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            called = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if called == func_name:
                out.append({kw.arg for kw in node.keywords if kw.arg})
    return out


def test_forecast_decide_declares_every_keyword_it_is_called_with():
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    declared = _params_of(tree, "_forecast_decide")
    for kwargs in _call_kwargs(tree, "_forecast_decide"):
        missing = kwargs - declared
        assert not missing, f"_forecast_decide вызывают с необъявленными доводами: {missing}"


def test_the_guard_bites_when_a_keyword_is_not_declared():
    """Сторож обязан падать на настоящей ошибке — иначе он украшение.

    Берём тот же исходник, но вычёркиваем объявленный довод из подписи, как это и
    было на живом прогоне (`military_names` передавали, а функция его не знала).
    """
    source = RUNNER.read_text(encoding="utf-8")
    broken = source.replace("                     military_names=None,\n", "", 1)
    assert broken != source, "подпись прогноза изменилась — правь этот сторож"
    tree = ast.parse(broken)
    declared = _params_of(tree, "_forecast_decide")
    seen = set().union(*_call_kwargs(tree, "_forecast_decide"))
    assert "military_names" in seen and "military_names" not in declared


def test_forecast_decide_passes_every_keyword_that_build_context_takes():
    """И довод обязан дойти до `build_context`: объявлен, но не передан — та же ошибка."""
    runner = ast.parse(RUNNER.read_text(encoding="utf-8"))
    live = ast.parse(LIVE.read_text(encoding="utf-8"))
    takes = _params_of(live, "build_context")
    calls = _call_kwargs(runner, "build_context")
    assert calls, "в раннере нет вызова build_context — проверка потеряла смысл"
    for kwargs in calls:
        unknown = kwargs - takes
        assert not unknown, f"build_context вызывают с необъявленными доводами: {unknown}"
        # Что прогноз объявляет у себя — то и должен передавать дальше, если оно есть у принимающего.
        declared = _params_of(runner, "_forecast_decide")
        expected = {k for k in declared if k in takes and k not in ("obs", "info", "dof", "extractor")}
        lost = expected - kwargs
        assert not lost, f"доводы прогноза не дошли до build_context: {lost}"