"""Работа клетки — строго выше простоя, но ниже основания города (§13.276).

Измерено: защитная рука за 20 ходов отправила `keep_activity` 125 раз и НИ РАЗУ работы
клетки, хотя `plant` стенд предлагал. Механизм тот же, что чинился у основания: набор
сравнивается `max(предпочтение, ΔDoF, обратимость)`, работа и простой давали равное
предпочтение, а по обратимости выигрывал простой.

Порядок: основание (+2) > работа (+1) > простой (0). Почему основание строго выше работы:
иначе поселенец, у которого доступны оба действия, начнёт строить дорогу вместо города.
Новых «своих» коэффициентов не вводится — обе надбавки уже приняты как правило «простой
не смеет обойти вложение в позицию» (13.271).

Идемпотентно.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "brain" / "generator" / "heuristics.py"

CONST_ANCHOR = """FOUNDING_ACTIONS = ('build_city', 'found_city')
"""
CONST_NEW = """FOUNDING_ACTIONS = ('build_city', 'found_city')

#: Работа клетки. Простой ход не смеет обойти её в паритете (§13.276): измерено —
#: защитная рука за 20 ходов 125 раз простояла и ни разу не улучшила клетку, хотя
#: `plant` стенд предлагал. Без работы клетки у города 1–2 жителей нет ни щитов, ни еды,
#: и любой тип строится десятки ходов (поселенец — 40, дисконт γ^40 роняет его желание).
TILE_WORK_ACTIONS = ('mine', 'irrigation', 'road', 'railroad', 'plant', 'cultivate')
"""

RET_OLD = """        score = float(sum(1 for pref in prefs if name.startswith(pref) or pref in name))
        if any(name.startswith(f) or f in name for f in FOUNDING_ACTIONS):
            # Основание города — решение ИГРЫ, а не доменная склонность (§13.270):
            # простой ход не смеет обойти его в паритете. Измерено на живой серии:
            # при равном предпочтении поселенец простаивал, потому что набор действий
            # сравнивается `max(предпочтение, ΔDoF, обратимость)`, основание необратимо,
            # а простой — обратим, и ход уходил простому.
            score += 1.0
        return score
"""

RET_NEW = """        score = float(sum(1 for pref in prefs if name.startswith(pref) or pref in name))
        # Паритет предпочтений решает ОБРАТИМОСТЬ (третий ключ сравнения), а простой
        # обратим — поэтому вложение в позицию обязано быть строго выше простоя.
        # Измерено дважды: поселенец простаивал вместо основания города (§13.270–13.271),
        # рабочие простояли 125 ходов и не улучшили ни клетки (§13.276).
        if any(name.startswith(f) or f in name for f in FOUNDING_ACTIONS):
            # Основание строго выше работы: иначе поселенец, у которого доступны оба
            # действия, начнёт строить дорогу вместо города.
            score += 2.0
        elif any(w in name for w in TILE_WORK_ACTIONS):
            score += 1.0
        return score
"""

text = PATH.read_text(encoding="utf-8")
changed = 0
for old, new in ((CONST_ANCHOR, CONST_NEW), (RET_OLD, RET_NEW)):
    if new in text:
        print("уже внесено")
        continue
    assert text.count(old) == 1, f"якорь не однозначен: {old[:60]!r}"
    text = text.replace(old, new)
    changed += 1

PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {changed}")

import ast  # noqa: E402
ast.parse(text)
print("синтаксис ок")
