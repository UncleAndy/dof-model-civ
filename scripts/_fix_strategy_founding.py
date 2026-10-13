"""Основание города — в список предпочтений КАЖДОЙ стратегии.

Иначе рука без DoF не основывает городов вовсе (измерено: счёт 0 против 7).
Правка идемпотентна: повторный запуск ничего не меняет.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "brain" / "generator" / "heuristics.py"

#: Старый список → новый. Ключ — подстрока старого списка (сама строка с отступом).
EDITS: list[tuple[str, str]] = [
    (
        "    preferred_unit_actions=['fortify', 'fortress', 'sentry', 'keep_activity'],\n",
        "    preferred_unit_actions=['build_city', 'found_city', 'fortify', 'fortress',\n"
        "                            'sentry', 'keep_activity'],\n",
    ),
    (
        "    preferred_unit_actions=['road', 'railroad', 'mine', 'plant', 'cultivate', 'goto'],\n",
        "    preferred_unit_actions=['build_city', 'found_city', 'road', 'railroad',\n"
        "                            'mine', 'plant', 'cultivate', 'goto'],\n",
    ),
    (
        "    preferred_unit_actions=['keep_activity', 'fortify', 'sentry'],\n",
        "    preferred_unit_actions=['build_city', 'found_city', 'keep_activity',\n"
        "                            'fortify', 'sentry'],\n",
    ),
]

text = PATH.read_text(encoding="utf-8")
total = 0
for old, new in EDITS:
    n = text.count(old)
    if n == 0:
        continue
    # `keep_activity`-список встречается дважды (technological и diplomatic) — правим оба.
    text = text.replace(old, new)
    total += n
    print(f"заменено {n}: {old.strip()[:60]}")

PATH.write_text(text, encoding="utf-8")
print(f"всего замен: {total}")

# Проверка результата: каждая стратегия обязана уметь основать город.
sys.path.insert(0, str(ROOT))
from brain.generator.heuristics import ALL_STRATEGIES  # noqa: E402

missing = [s.name for s in ALL_STRATEGIES
           if not any(a in ("build_city", "found_city") for a in s.preferred_unit_actions)]
if missing:
    print(f"ОШИБКА: без основания остались: {missing}")
    raise SystemExit(1)
print("проверка: основание есть у всех стратегий")
