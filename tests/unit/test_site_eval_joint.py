"""§13.320: площадка оценивается ОДНОЙ совместной расстановкой, а не тремя независимыми наборами.

Данные ниже — не выдумка: это 21 рабочая клетка нашего единственного города из длинной
партии 2026-10-14 (срез `dof_state_dump.jsonl`, город (57,28), размер 4), снятые с живого
стенда. На них видно то, ради чего сторож и написан: независимый набор обещает «еда 10 и
щиты 5», тогда как город физически не может работать обе четвёрки клеток — совместная
расстановка даёт «еда 8, щиты 3».
"""
from __future__ import annotations

import itertools

from env.site_eval import joint_site_outputs

#: (еда, щиты, торговля) — центр первым, как их отдаёт читатель карты.
REAL_TILES: list[tuple[float, float, float]] = [
    (1.0, 1.0, 0.0),   # центр (0,0)
    (0.0, 1.0, 0.0),   # (0,-1)
    (2.0, 0.0, 0.0),   # (-1,0)
    (1.0, 0.0, 0.0),   # (1,0)
    (2.0, 0.0, 0.0),   # (0,1)
    (3.0, 0.0, 1.0),   # (-1,-1)
    (1.0, 0.0, 0.0),   # (1,-1)
    (1.0, 0.0, 0.0),   # (-1,1)
    (1.0, 0.0, 0.0),   # (1,1)
    (1.0, 0.0, 0.0),   # (0,-2)
    (1.0, 1.0, 0.0),   # (-2,0)
    (0.0, 1.0, 0.0),   # (2,0)
    (1.0, 0.0, 0.0),   # (0,2)
    (1.0, 0.0, 0.0),   # (-1,-2)
    (0.0, 1.0, 0.0),   # (1,-2)
    (0.0, 1.0, 0.0),   # (-2,-1)
    (1.0, 0.0, 0.0),   # (2,-1)
    (0.0, 1.0, 0.0),   # (-2,1)
    (2.0, 0.0, 0.0),   # (2,1)
    (1.0, 0.0, 0.0),   # (-1,2)
    (1.0, 1.0, 0.0),   # (1,2)
]

SIZE = 4
FOOD_COST = 2.0


def _independent(tiles: list[tuple[float, float, float]], need: int) -> tuple[float, float]:
    """То, как площадку считает `evaluate_site`: ресурсы НЕЗАВИСИМО, одни клетки дважды."""
    by_food = sorted(tiles, key=lambda t: (t[0], t[1]), reverse=True)[:need]
    by_shield = sorted(tiles, key=lambda t: (t[1], t[0]), reverse=True)[:need]
    return sum(t[0] for t in by_food), sum(t[1] for t in by_shield)


def test_joint_arrangement_feeds_the_city() -> None:
    food, _shields, _trade, fed = joint_site_outputs(REAL_TILES, SIZE, FOOD_COST)
    assert fed is True
    assert food >= FOOD_COST * SIZE, "совместная расстановка обязана кормить размер"


def test_joint_is_never_richer_than_the_independent_sum() -> None:
    """Независимый набор — верхняя граница: он не может быть беднее совместного."""
    food, shields, _trade, _fed = joint_site_outputs(REAL_TILES, SIZE, FOOD_COST)
    ind_food, ind_shields = _independent(REAL_TILES, SIZE + 1)
    assert ind_food >= food
    assert ind_shields >= shields


def test_live_site_inflation_is_what_the_guard_is_for() -> None:
    """Завышение щитов на живой площадке — измеренная величина, а не рассуждение."""
    food, shields, _trade, fed = joint_site_outputs(REAL_TILES, SIZE, FOOD_COST)
    ind_food, ind_shields = _independent(REAL_TILES, SIZE + 1)
    assert (food, shields) == (8.0, 3.0)
    assert (ind_food, ind_shields) == (10.0, 5.0)
    assert ind_shields - shields == 2.0, "щиты завышены на 2 (5 против 3)"
    assert ind_food - food == 2.0


def test_best_food_and_best_shield_tiles_are_disjoint_here() -> None:
    """Корень завышения: лучшие по еде клетки — не те, что лучшие по щитам."""
    rest = REAL_TILES[1:]
    food_best = {i for i, _ in sorted(
        enumerate(rest), key=lambda p: (p[1][0], p[1][1]), reverse=True)[:SIZE]}
    shield_best = {i for i, _ in sorted(
        enumerate(rest), key=lambda p: (p[1][1], p[1][0]), reverse=True)[:SIZE]}
    assert food_best & shield_best == set(), "пересечение должно быть пустым — иначе завышения нет"


def test_centre_is_always_worked() -> None:
    """Центр — бесплатная клетка города: он входит в расстановку при любом размере."""
    centre = (9.0, 9.0, 0.0)
    tiles = [centre] + [(0.0, 0.0, 0.0)] * 20
    food, shields, _trade, _fed = joint_site_outputs(tiles, 3, FOOD_COST)
    assert food >= 9.0 and shields >= 9.0


def test_unfeedable_site_is_reported_not_hidden() -> None:
    """Площадка, которую нельзя прокормить, обязана быть видна флагом, а не нулём."""
    tiles = [(0.0, 1.0, 0.0)] + [(0.0, 2.0, 0.0)] * 20
    food, shields, _trade, fed = joint_site_outputs(tiles, 4, FOOD_COST)
    assert fed is False
    assert shields > 0.0, "нужды не прячем: щиты есть, но город при них голодает"


def test_brute_force_matches_the_helper() -> None:
    """Сторож против второго определения: перебор в тесте и функция обязаны совпасть."""
    rest = REAL_TILES[1:]
    best_key: tuple[float, float] | None = None
    for combo in itertools.combinations(rest, SIZE):
        chosen = [REAL_TILES[0]] + list(combo)
        f = sum(t[0] for t in chosen)
        s = sum(t[1] for t in chosen)
        if f < FOOD_COST * SIZE:
            continue
        if best_key is None or (s, f) > best_key:
            best_key = (s, f)
    assert best_key is not None
    food, shields, _trade, _fed = joint_site_outputs(REAL_TILES, SIZE, FOOD_COST)
    assert (shields, food) == best_key
