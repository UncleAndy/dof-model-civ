"""Сборка вариантов работ для клетки из правил мира (§13.287).

Нужна, чтобы перенесённый `choose_tile_work` получал то, что в исходнике даёт кэш
(`initialize_infrastructure_cache`, `infracache.c:242`): ценность клетки ПОСЛЕ работы.
В исходнике она считается на ВИРТУАЛЬНОЙ клетке после перехода рельефа; у нас переход
выражен приростами из правил мира (`env/terrain_work_effects.py`), а срок — временами из
тех же правил (`env/terrain_work_times.py`, поля `common/terrain.h:215-227`).

Что включено и почему:

* `mine` → `mining_shield_incr` — прирост щитов из правил;
* `irrigation` → `irrigation_food_incr` — прирост еды из правил.

Что НЕ включено: дороги. Их прирост выражен в правилах процентом по террейну
(`road_trade_incr_pct`) плюс собственным приростом экстры (`road.trade_incr`), и связка
«процент от чего именно» должна быть проверена отдельным замером, а не предположена.
Пока включены две работы с прямым приростом — и это ровно та пара, которой решается рост
(орошение за еду против шахты за щиты).

Работы, которых нет в правилах для этого террейна, не предлагаются вовсе: ноль в правилах
означает «нельзя», а не «мгновенно».

Идемпотентно.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "brain" / "ai_default" / "worker_choice.py"

FUNC = '''

#: Работа → поле правил, которым выражен её прирост, и статья выхода, которую оно двигает.
WORK_INCREMENT_FIELDS: dict[str, tuple[str, int]] = {
    "mine": ("mining_shield_incr", 1),          # индекс 1 — щиты в тройке (food, shield, trade)
    "irrigation": ("irrigation_food_incr", 0),  # индекс 0 — еда
}


def work_options_from_rules(terrain: str, outputs, offered) -> dict:
    """Варианты работ для клетки: `{работа: (новая тройка выходов, срок)}` — из правил мира.

    Вход: террейн клетки, её текущие выходы `(food, shield, trade)` и имена работ, которые
    стенд СЕЙЧАС предлагает. Выход — только те работы, у которых в правилах есть прирост и
    есть срок: «нельзя» никогда не выглядит как «мгновенно».

    Срок берётся из правил террейна (`env/terrain_work_times.py`), потому что перенесённое
    правило встроенного ИИ дисконтирует выигрыш по числу ходов: `amortize(total, delay)`.
    """
    from env.terrain_work_effects import TERRAIN_WORK_EFFECTS
    from env.terrain_work_times import TERRAIN_WORK_TIMES

    effects = TERRAIN_WORK_EFFECTS.get(str(terrain), {}) or {}
    times = TERRAIN_WORK_TIMES.get(str(terrain), {}) or {}
    out: dict = {}
    for work in offered:
        name = str(work)
        field = WORK_INCREMENT_FIELDS.get(name)
        if field is None:
            continue
        key, index = field
        if key not in effects or name not in times:
            continue
        delta = float(effects[key])
        if delta == 0:
            continue
        new_outputs = list(outputs)
        new_outputs[index] = new_outputs[index] + delta
        out[name] = (tuple(new_outputs), int(times[name]))
    return out
'''

text = PATH.read_text(encoding="utf-8")
if "def work_options_from_rules(" in text:
    print("уже внесено")
else:
    PATH.write_text(text.rstrip() + FUNC, encoding="utf-8")
    print("сборка вариантов внесена")

import ast  # noqa: E402
ast.parse(PATH.read_text(encoding="utf-8"))
print("синтаксис ок")
