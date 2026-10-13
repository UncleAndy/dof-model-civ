"""Основание города не смеет обойти простой ход (§13.270, продолжение).

`_preference_score` — счёт совпадений со списком, порядок там не значит ничего.
Поэтому основание и простой давали РАВНОЕ предпочтение, а набор действий сравнивается
как `max(предпочтение, ΔDoF, обратимость)`: по обратимости простой выигрывал, потому что
основание необратимо. Измерено на живой серии: поселенец ходил `keep_activity`.

Правка идемпотентна: повторный запуск ничего не меняет.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "brain" / "generator" / "heuristics.py"

CONST_ANCHOR = "ALL_STRATEGIES = [DEFENSIVE, EXPANSIONIST, ECONOMIC, TECHNOLOGICAL, DIPLOMATIC]\n"
CONST_BLOCK = CONST_ANCHOR + '''
#: Действия основания города. Оба имени в ходу: агент синтезирует `build_city`,
#: спецификация роли зовёт его `found_city`.
FOUNDING_ACTIONS = ('build_city', 'found_city')
'''

OLD_RETURN = (
    "        return float(sum(1 for pref in prefs if name.startswith(pref) or pref in name))\n"
)
NEW_RETURN = '''        score = float(sum(1 for pref in prefs if name.startswith(pref) or pref in name))
        if any(name.startswith(f) or f in name for f in FOUNDING_ACTIONS):
            # Основание города — решение ИГРЫ, а не доменная склонность (§13.270):
            # простой ход не смеет обойти его в паритете. Измерено на живой серии:
            # при равном предпочтении поселенец простаивал, потому что набор действий
            # сравнивается `max(предпочтение, ΔDoF, обратимость)`, основание необратимо,
            # а простой — обратим, и ход уходил простому.
            score += 1.0
        return score
'''

text = PATH.read_text(encoding="utf-8")
changed = 0

if "FOUNDING_ACTIONS = (" not in text:
    assert text.count(CONST_ANCHOR) == 1, "не найден однозначный якорь ALL_STRATEGIES"
    text = text.replace(CONST_ANCHOR, CONST_BLOCK)
    changed += 1

n = text.count(OLD_RETURN)
assert n == 1, f"ожидалась одна точка возврата, найдено {n}"
text = text.replace(OLD_RETURN, NEW_RETURN)
changed += 1

PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {changed}")

sys.path.insert(0, str(ROOT))
from brain.generator.heuristics import ALL_STRATEGIES, HeuristicGenerator  # noqa: E402

bad = []
for strategy in ALL_STRATEGIES:
    gen = HeuristicGenerator(strategy=strategy)
    found = gen._preference_score({"action_name": "build_city", "ctrl_type": "unit"})
    idle = gen._preference_score({"action_name": "keep_activity", "ctrl_type": "unit"})
    print(f"  {strategy.name:<16} основание={found:.1f} простой={idle:.1f}")
    if not found > idle:
        bad.append(strategy.name)
if bad:
    print(f"ОШИБКА: основание не выше простоя у {bad}")
    raise SystemExit(1)
print("проверка: основание строго выше простоя у всех стратегий")
