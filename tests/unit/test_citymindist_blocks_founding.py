"""Сторож правила `citymindist`: основание запрещено ближе, чем город (`common/city.c:1445`).

Правило перенесено буквально: `square_iterate(ptile, citymindist - 1)` — любой город внутри
квадрата со стороной `2*(mindist-1)+1` запрещает основание. Проверка нужна потому, что мир
отказывает в основании именно по нему, а наша оценка площадки его не знала.
"""

from __future__ import annotations


def test_within_the_ring_is_blocked() -> None:
    from brain.ai_default.founder_destination import citymindist_blocks

    cities = [(10, 10)]
    assert citymindist_blocks(10, 10, cities, 2)          # сама клетка города
    assert citymindist_blocks(11, 10, cities, 2)          # соседняя по оси
    assert citymindist_blocks(9, 11, cities, 2)           # соседняя по диагонали
    assert not citymindist_blocks(12, 10, cities, 2)      # ровно на расстоянии 2 — можно
    assert not citymindist_blocks(10, 13, cities, 2)


def test_mindist_one_allows_adjacent() -> None:
    from brain.ai_default.founder_destination import citymindist_blocks

    cities = [(10, 10)]
    assert citymindist_blocks(10, 10, cities, 1)          # «минимум 1 — соседняя годится»
    assert not citymindist_blocks(11, 11, cities, 1)


def test_mindist_zero_blocks_nothing() -> None:
    from brain.ai_default.founder_destination import citymindist_blocks

    assert not citymindist_blocks(10, 10, [(10, 10)], 0)


def test_ring_is_built_for_every_city() -> None:
    from brain.ai_default.founder_destination import citymindist_blocks

    cities = [(10, 10), (40, 40)]
    assert citymindist_blocks(39, 39, cities, 3)          # вокруг ВТОРОГО города
    assert not citymindist_blocks(25, 25, cities, 3)


def test_rank_sites_accepts_cities_and_mindist() -> None:
    """Новые параметры не ломают выбор площадок и по пустому миру дают пусто."""
    from brain.ai_default.founder_destination import rank_sites

    assert rank_sites({}, revealed=[], cities=[(10, 10)], mindist=2) == []
