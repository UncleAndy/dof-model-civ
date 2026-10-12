"""Ветвь эксперимента (§13.262): малому городу улучшения не предлагаются — только единицы.

Повод: 33 из 63 решений производства — `Barracks`. У города размера 1–2 при выходе 1–2 щита казарма
(около сорока щитов) выбирает весь выход за 20–30 ходов. По коду встроенного ИИ у казармы в мирное
время нет причины: его `domestic_advisor_choose_build` берёт постройку только при хотении выше
желания поселенца/рабочего, а смена постановки ещё и стоит щитов (`v -= shield_stock * 17/15`).

Ветвь включается переменной `DOF_SMALL_CITY_UNITS_ONLY=1` и печатает признак (иначе «эффекта нет» и
«ветвь не подключена» неразличимы). Различие с объявленным порогом: отбор действует для городов
размера ≤ 2 в течение ВСЕЙ партии, а не только первых 20 ходов — так ветвь не зависит от номера хода,
которого у контекста нет. Это различие объявлено, а не спрятано.
"""
from __future__ import annotations

import pathlib

LIVE = pathlib.Path("/home/hermes/projects/AI/DOF-MODEL-CIV/brain/forecast/live.py")

src = LIVE.read_text(encoding="utf-8")
OLD = '''        rec = city_records.get(city_id) or {}'''
NEW = '''        rec = city_records.get(city_id) or {}
        # ВЕТВЬ ЭКСПЕРИМЕНТА (§13.262): городам размера ≤ 2 улучшения не предлагаются вовсе —
        # только единицы (поселенец, рабочий, защитник). Проверяем объявленное: казарма съедает
        # выход малого города (33 решения из 63), отчего город стоит без роста 20–30 ходов.
        if os.environ.get("DOF_SMALL_CITY_UNITS_ONLY") == "1":
            _sz_scuo = int(_num(rec.get("size"), 0) or 0)
            if 0 < _sz_scuo <= 2:
                _EXPERIMENT_STATS["small_city_improvements_skipped"] = \\
                    _EXPERIMENT_STATS.get("small_city_improvements_skipped", 0) + 1
                if os.environ.get("DOF_TRACE_FILTERS") == "1":
                    print(f"        [ветвь] городу {city_id} размера {_sz_scuo} улучшения "
                          f"не предлагаются (§13.262)", flush=True)
                return []'''
assert OLD in src, "место начала improvements() не найдено"
assert src.count(OLD) == 1, "место не уникально"
src = src.replace(OLD, NEW, 1)

# Счётчик ветви — рядом с прочими счётчиками прогноза.
if "_EXPERIMENT_STATS" not in src.split("def improvements")[0]:
    anchor = "def _num("
    idx = src.find(anchor)
    assert idx > 0, "не найдено место для счётчика"
    head, tail = src[:idx], src[idx:]
    head = head.rstrip() + "\n\n\n#: Счётчики ветвей-экспериментов (печатаются по DOF_TRACE_FILTERS).\n_EXPERIMENT_STATS: dict[str, int] = {}\n\n\n"
    src = head + tail
LIVE.write_text(src, encoding="utf-8")
print("ветвь DOF_SMALL_CITY_UNITS_ONLY встроена")
