"""Сторож на порог годности площадки: он падает с ходом ДЛЯ ВСЕХ городов.

Измерено (§13.165): пока убывание касалось только первого города, после его основания
порог возвращался к 6.0, а на бедной земле (три лучшие клетки дают 3.0) это значило
«годных площадок 0 из 48» — расширение запрещалось целиком. Решение владельца
(2026-10-12): продлить тот же закон на все города.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from env.config import (SITE_MIN_FOOD, SITE_MIN_FOOD_FIRST,
                        SITE_MIN_FOOD_FIRST_DECAY, SITE_MIN_FOOD_FIRST_FLOOR,
                        first_city_food_gate)

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_gate_starts_at_the_declared_value():
    assert SITE_MIN_FOOD_FIRST == SITE_MIN_FOOD == 6.0
    assert first_city_food_gate(1) == pytest.approx(6.0)


def test_the_gate_falls_by_the_declared_step():
    step = SITE_MIN_FOOD_FIRST_DECAY
    assert step == pytest.approx(0.4)
    assert first_city_food_gate(4) == pytest.approx(6.0 - 3 * step)   # 4.8
    assert first_city_food_gate(9) == pytest.approx(6.0 - 8 * step)   # 2.8


def test_the_gate_stops_at_the_declared_floor():
    assert first_city_food_gate(14) == pytest.approx(SITE_MIN_FOOD_FIRST_FLOOR)
    assert first_city_food_gate(150) == pytest.approx(SITE_MIN_FOOD_FIRST_FLOOR)
    assert first_city_food_gate(0) == pytest.approx(6.0)  # ход < 1 трактуется как первый


def _site_vals_is_unconditional() -> bool:
    """Применяется ли порог в `_site_vals` без оглядки на «городов нет».

    Читаем исходник, а не поведение: поведенческий тест потребовал бы живого
    наблюдения карты, которого в модульных тестах нет.
    """
    src = (ROOT / "env" / "entity_extractor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_site_vals":
            for stmt in ast.walk(node):
                if (isinstance(stmt, ast.If)
                        and "_no_cities" in ast.dump(stmt.test)):
                    return False
            return True
    raise AssertionError("_site_vals не найдена — тест устарел")


def test_the_gate_applies_to_every_city_not_only_the_first():
    assert _site_vals_is_unconditional(), (
        "порог снова применяется только пока городов нет: на бедной земле это "
        "запрещает все последующие города (§13.165)")


def test_the_live_forecast_takes_the_gate_from_one_place():
    """И прогноз, и прежний путь обязаны брать порог из `first_city_food_gate`."""
    live = (ROOT / "brain" / "forecast" / "live.py").read_text(encoding="utf-8")
    assert "first_city_food_gate(" in live
    assert "SITE_MIN_FOOD\"] = _cfg.first_city_food_gate" in live
    ext = (ROOT / "env" / "entity_extractor.py").read_text(encoding="utf-8")
    assert "_first_city_food_gate(" in ext