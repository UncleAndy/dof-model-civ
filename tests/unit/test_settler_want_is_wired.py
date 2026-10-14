"""Сторож: перенесённая `settler_want` обязана быть ВЫЗВАНА, а не лежать мёртвой.

Повод — измеренный факт (§13.301): функция была перенесена из `daisettler.c`
построчно и **не вызывалась нигде**, решение об основании города жило на нашей
выдуманной формуле `best_raw / (1 + dist/3)`. Это тот же класс, что уже трижды
встречался в проекте: перенесённый механизм есть в дереве, но общий путь его не
вызывает, и на стенде он не действует вовсе.

Сторож дешёвый и нарочно грубый: он не даёт «перенести и забыть» на уровне
исходника, потому что поведенческий тест здесь потребовал бы целого стенда.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_settler_want_is_called_from_founder_want():
    """`settler_want` вызывается там, где решается цена поселенца."""
    text = (ROOT / "brain" / "forecast" / "live.py").read_text(encoding="utf-8")
    assert "settler_want" in text, (
        "перенесённая `settler_want` нигде не вызывается — цена поселенца "
        "считается не формулой встроенного ИИ"
    )
    assert "_settler_want(" in text, "`settler_want` не вызывается, а только импортируется"


def test_the_invented_formula_is_gone():
    """Наша выдуманная формула срока убрана: `best_raw / (1 + dist/3)`."""
    text = (ROOT / "brain" / "forecast" / "live.py").read_text(encoding="utf-8")
    assert "1.0 + float(dist) / perf" not in text, (
        "вернулась выдуманная формула дисконта вместо `amortize(total, PERFECTION*ходов)`"
    )


def test_his_constants_are_not_redeclared_locally():
    """`PERFECTION` берётся из перенесённых значений, а не выписывается снова в живом пути."""
    text = (ROOT / "brain" / "forecast" / "live.py").read_text(encoding="utf-8")
    assert "perf = 3  # PERFECTION" not in text, (
        "PERFECTION снова выписан числом в живом пути вместо общего перенесённого значения"
    )
