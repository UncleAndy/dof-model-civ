"""Сторож на удержание решения по клетке: обратный ход к своему же не отправляем.

Пойманная ошибка (§13.232, покадровый след): житель города снимался и ставился на ту же
клетку КАЖДЫЙ ход — `city_unwork_18_1_2` и `city_work_18_1_2` чередовались. При снятом
жителе прирост еды становится +0, и мир отдаёт «рост через 1000000000 turns» (признак
остановленного роста), а счётчик производства сбрасывается (5 → 29 ходов). Города
остаются на двух при 5 у встроенного ИИ.

Удержание постановки (§13.196/§13.230) на клетки не распространялось. Путь живого матча в
тестах не исполняется (дорог), поэтому проверка статическая — как в
`test_production_hold_silence.py`.
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = ROOT / "baselines" / "run_real_tournament.py"


def _tile_hold_paths() -> list[tuple[str, str]]:
    """Найти в решении прогноза (a) память о клетке и (b) отказ от обратного хода."""
    src = RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_forecast_decide":
            seg = ast.get_source_segment(src, node) or ""
            has_memory = "_LAST_TILE_ACTION" in seg
            has_refusal = "city_unwork_" in seg and "city_work_" in seg
            out.append(("память" if has_memory else "нет памяти",
                        "отказ" if has_refusal else "нет отказа"))
    return out


def test_tile_decision_holds_against_flip_flop():
    """В решении прогноза обязана быть память по клетке И отказ от обратного хода."""
    paths = _tile_hold_paths()
    assert paths, "решение прогноза `_forecast_decide` не найдено — сторож ослеп"
    for memory, refusal in paths:
        assert memory == "память", (
            "в решении прогноза нет памяти о последнем действии по клетке: житель снова "
            "сможет дёргаться туда-обратно каждый ход (§13.232)."
        )
        assert refusal == "отказ", (
            "в решении прогноза нет отказа от обратного хода по клетке: "
            "`city_unwork_*` после `city_work_*` той же клетки пройдёт насквозь (§13.232)."
        )