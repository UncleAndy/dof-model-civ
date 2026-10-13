"""Сторож на перенос выбора работы (§13.285).

Источник: `server/advisors/autoworkers.c` закреплённого коммита freeciv
(`consider_settler_action` стр. 308, обход — стр. 439, `WORKER_FACTOR` стр. 70).

Проверяются ПРАВИЛА исходника, а не «здравый смысл»: именно они решают, какую работу
сделает рабочий, и именно их отсутствие держало город на размере 1 (13.280).

ВАЖНО про две ветки исходника — их различие я сам сначала перепутал:

* клетка, которая НЕ обрабатывается городом (`!in_use`), и лучшая ещё не «в работе»:
  сравнивается ПОЛНАЯ ценность новой клетки — по его комментарию, «получить лучший итог
  для следующего горожанина важнее, чем величина улучшения» (стр. 344-361);
* иначе — сравнивается ПРИРОСТ (`new − old`), с делением на 2 для необрабатываемой клетки,
  и выигрыш амортизируется по числу ходов (стр. 363-402).

Первая версия этих тестов ждала прироста там, где исходник сравнивает итог. Тесты
исправлены ПОД ИСХОДНИК; порт не подгонялся.
"""
from __future__ import annotations

import pathlib

import pytest

from brain.ai_default.worker_choice import (
    WORKER_FACTOR, choose_tile_work, consider_settler_action, empty_choice,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "drafts" / "reference" / "freeciv-src" / "server" / "advisors" / "autoworkers.c"


def test_zero_benefit_work_is_never_chosen():
    """`best_newv = 0` в исходнике: работа, которая ничего не улучшает, не выбирается."""
    tiles = [((1, 1), (2, 0, 0), {"mine": ((2, 0, 0), 3)})]
    assert choose_tile_work(tiles).activity == ""


def test_improving_work_is_chosen():
    tiles = [((1, 1), (2, 0, 0), {"irrigation": ((3, 0, 0), 3)})]
    choice = choose_tile_work(tiles)
    assert choice.activity == "irrigation"
    assert choice.tile == (1, 1)
    assert choice.delay == 3


def test_food_beats_shields_when_both_tiles_are_in_use():
    """Ветка прироста: +1 еды (вес 30) против +1 щита (вес 17) — еда обязана выиграть."""
    tiles = [
        ((1, 1), (2, 1, 0), {"mine": ((2, 2, 0), 3)}),        # +1 щит: 17
        ((2, 2), (2, 0, 0), {"irrigation": ((3, 0, 0), 3)}),  # +1 еда: 30
    ]
    choice = choose_tile_work(tiles, in_use_tiles=frozenset({(1, 1), (2, 2)}))
    assert choice.activity == "irrigation", choice


def test_unworked_tile_prefers_the_best_total_not_the_gain():
    """Стр. 344-361: у необрабатываемой клетки сравнивается ИТОГ, а не улучшение.

    Клетка с +1 щитом и итогом 117.5 обязана победить клетку с +1 едой и итогом 105 —
    хотя прирост у них разный по весам. Это его выбор, и он записан его же словами.
    """
    tiles = [
        ((1, 1), (2, 1, 0), {"mine": ((2, 2, 0), 3)}),        # итог 117.5
        ((2, 2), (2, 0, 0), {"irrigation": ((3, 0, 0), 3)}),  # итог 105
    ]
    assert choose_tile_work(tiles).tile == (1, 1)


def test_equal_total_prefers_the_bigger_gain():
    """`old_tile_value < *best_old_tile_value` при равной новой ценности — дословно.

    Равный итог, но старая ценность ниже ⇒ прирост больше ⇒ такая клетка и выбирается.
    """
    tiles = [
        ((1, 1), (3, 0, 0), {"irrigation": ((3, 0, 0), 2)}),  # итог равен старому: не улучшает
        ((2, 2), (2, 0, 0), {"irrigation": ((3, 0, 0), 2)}),  # улучшает: 75 → 105
    ]
    choice = choose_tile_work(tiles)
    assert choice.tile == (2, 2), choice


def test_in_use_gain_is_not_halved_and_wins_over_unworked():
    """`if (!in_use) total_value /= 2;` — дословно из исходника (ветка прироста)."""
    tiles = [
        ((1, 1), (2, 0, 0), {"irrigation": ((3, 0, 0), 2)}),  # не обрабатывается: прирост /2
        ((2, 2), (2, 0, 0), {"irrigation": ((3, 0, 0), 2)}),  # обрабатывается: прирост целиком
    ]
    assert choose_tile_work(tiles, in_use_tiles=frozenset({(2, 2)})).tile == (2, 2)


def test_earlier_delay_wins_when_gains_are_equal():
    """`amortize(total, delay)` — выигрыш дисконтируется по числу ходов (ветка прироста)."""
    tiles = [
        ((1, 1), (2, 0, 0), {"irrigation": ((3, 0, 0), 9)}),
        ((2, 2), (2, 0, 0), {"irrigation": ((3, 0, 0), 2)}),
    ]
    choice = choose_tile_work(tiles, in_use_tiles=frozenset({(1, 1), (2, 2)}))
    assert choice.tile == (2, 2), choice


def test_empty_choice_mirrors_the_source_initial_values():
    """`best_newv = 0`, `best_oldv = 9999` — начальное «лучшее» из исходника."""
    c = empty_choice()
    assert c.value == 0.0 and c.old_value == 9999


def test_worker_factor_is_the_source_value():
    assert WORKER_FACTOR == 1024


def test_source_still_says_the_same():
    """Сторож на источник: разошёлся он — копия под подозрением."""
    if not SOURCE.exists():
        pytest.skip("исходник freeciv не выложен локально (drafts/reference/freeciv-src)")
    text = SOURCE.read_text(encoding="utf-8", errors="replace")
    assert "#define WORKER_FACTOR 1024" in text
    assert "static void consider_settler_action" in text
    assert "total_value = base_value * WORKER_FACTOR;" in text
    assert "total_value /= 2;" in text
    assert "total_value = amortize(total_value, delay);" in text
    assert "Getting the best possible total for next citizen to work on is more" in text
