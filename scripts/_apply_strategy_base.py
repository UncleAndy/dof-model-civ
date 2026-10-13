"""Внести базовые рода решений в список КАЖДОЙ руки (§13.275).

При `--no-dof` список работает РАЗРЕШЕНИЕМ, а не склонностью: `_preference_score` — счёт
совпадений, веса стратегий умножают выключенный DoF-выигрыш. Рука без рода в списке
структурно не способна этот род выбрать; измерено — expansionist 5.7 против defensive 1.0
на полных 20 ходах, при том что у оборонительной нет ни одной работы клетки и ни одного
`goto`.

База: основание города, ПОЛНЫЙ набор работ клетки, ход/раскрытие тумана. Что доступно,
решает местность, а не наша догадка. Свои склонности остаются СВЕРХ базы; ничего не
убирается. Правка идемпотентна.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "brain" / "generator" / "heuristics.py"

BASE = ("'build_city', 'found_city', 'road', 'railroad', 'mine',\n"
        "                            'irrigation', 'plant', 'cultivate', 'goto'")


def _armed(extras: tuple[str, ...]) -> str:
    tail = "".join(f", '{e}'" for e in extras)
    return (f"    preferred_unit_actions=[{BASE}{tail}],\n")


EDITS: list[tuple[str, str, int]] = [
    # (что искать, на что заменить, сколько вхождений ожидаем)
    (
        "    preferred_unit_actions=['build_city', 'found_city', 'fortify', 'fortress',\n"
        "                            'sentry', 'keep_activity'],\n",
        _armed(("fortify", "fortress", "sentry", "keep_activity")),
        1,
    ),
    (
        "    preferred_unit_actions=['found_city', 'build_city', 'road', 'railroad', 'goto', 'irrigation'],\n",
        _armed(()),
        1,
    ),
    (
        "    preferred_unit_actions=['build_city', 'found_city', 'road', 'railroad',\n"
        "                            'mine', 'plant', 'cultivate', 'goto'],\n",
        _armed(()),
        1,
    ),
    (
        "    preferred_unit_actions=['build_city', 'found_city', 'keep_activity',\n"
        "                            'fortify', 'sentry'],\n",
        _armed(("keep_activity", "fortify", "sentry")),
        2,  # technological и diplomatic
    ),
]

text = PATH.read_text(encoding="utf-8")
total = 0
for old, new, expected in EDITS:
    n = text.count(old)
    if n == 0:
        print(f"пропуск (уже внесено): {old.split('=')[1][:40]}...")
        continue
    assert n == expected, f"ждали {expected} вхождений, нашли {n}: {old[:50]}"
    text = text.replace(old, new)
    total += n
    print(f"заменено {n}")

PATH.write_text(text, encoding="utf-8")
print(f"всего замен: {total}")

import ast  # noqa: E402
ast.parse(text)

import sys  # noqa: E402
sys.path.insert(0, str(ROOT))
from brain.generator.heuristics import ALL_STRATEGIES  # noqa: E402

for s in ALL_STRATEGIES:
    print(f"  {s.name:<15} {s.preferred_unit_actions}")
