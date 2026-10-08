"""Страж текста: посторонние символы в записанных файлах.

Зачем файлом, а не строчкой в каждом вызове: набор разрешённого переписывался по памяти
и четырежды за сессию 2026-10-08 страж спотыкался о **намеренную** типографику проекта
(«» — – …, затем `−` в числах, затем `Δ` из самой спецификации). Разрешённое объявляется
здесь один раз; вызов: `.venv/bin/python scripts/_scan_text.py <файлы…>`.

Разрешено: ASCII, кириллица, греческий (символы спецификации: Δ, ε, τ, ψ, λ, μ, σ), стрелки,
рамки, геометрические фигуры. Всё прочее — постороннее и роняет проверку: смысл в том, чтобы
искажение письма ловилось **до** запуска записанного, а не глазами по отображению вызова.
"""
from __future__ import annotations

import pathlib
import sys
import unicodedata

#: Типографский набор, который проект употребляет намеренно.
TYPOGRAPHY = "«»„“”‘’—–−…·•№§°±×÷≤≥≈≠"

#: Блоки, которые проект употребляет намеренно (диапазоны кодпоинтов).
ALLOWED_RANGES: tuple[tuple[int, int], ...] = (
    (0x0370, 0x03FF),   # греческий: Δ, ε, τ, ψ, λ, μ, σ
    (0x1F00, 0x1FFF),   # греческий расширенный
    (0x2190, 0x21FF),   # стрелки: →, ←
    (0x2500, 0x257F),   # рамки: ─, │, ┌
    (0x25A0, 0x25FF),   # геометрические фигуры: ▪
)


def foreign(text: str) -> dict[str, str]:
    """Посторонние символы: символ -> его имя. Пусто — текст чист."""
    out: dict[str, str] = {}
    for ch in text:
        if ch.isascii() or ch in TYPOGRAPHY:
            continue
        if any(lo <= ord(ch) <= hi for lo, hi in ALLOWED_RANGES):
            continue
        name = unicodedata.name(ch, "?")
        if "CYRILLIC" in name:
            continue
        out[ch] = name
    return out


def main(paths: list[str]) -> int:
    bad: dict[str, dict[str, str]] = {}
    for raw in paths:
        got = foreign(pathlib.Path(raw).read_text(encoding="utf-8"))
        if got:
            bad[raw] = got
    print("посторонние символы:", bad if bad else "нет")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
