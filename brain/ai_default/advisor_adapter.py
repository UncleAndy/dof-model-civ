"""Адаптер советников: ранжированные варианты мира → три советника каркаса `choose_build`.

Каркас выбора производства (`brain/ai_default/build_choice.py`) ждёт трёх советников —
военного, внутреннего и поселенца, — и от КАЖДОГО по имени производства сырое желание.
Здесь только развязка: то, что уже посчитано по имени (его же шкала, `daicity.c:1421`
`dai_city_want` / `improvement_value`), раскладывается по ведомствам без пересчёта чисел.
Новых коэффициентов здесь нет — иначе «перенос» снова стал бы своей оценкой.

Зачем отдельным модулем. Ветвь «его выбор» в раннере берёт список `(имя, желание, срок)` из
`brain/forecast/live.py:production_of` и до сих пор САМА выбирала из него, своими фильтрами.
Каркас выбирает той же шкалой, что и он. Развязка по ведомствам вынесена сюда, чтобы её можно
было проверить юнит-тестами без игры — как и сам каркас.
"""

from __future__ import annotations

#: Роли поселенца у него (`ACTION_FOUND_CITY`); имена — как их печатает стенд.
FOUNDER_NAMES: tuple[str, ...] = ("Settlers", "Founder", "Found City")


def split_options(options, *, military_names=(), founder_names=FOUNDER_NAMES):
    """Разложить `[(имя, желание, срок), ...]` по трём ведомствам каркаса.

    Военное — по списку боевых типов мира; поселенческое — по ролям основания; всё прочее —
    внутреннее ведомство (постройки, рабочие, торговцы). Возвращает три словаря
    `{имя: сырое желание}` — ровно то, что каркас ждёт от советников.
    """
    mil_set = {str(x) for x in (military_names or ())}
    found_set = {str(x) for x in (founder_names or ())}
    military: dict[str, float] = {}
    domestic: dict[str, float] = {}
    founder: dict[str, float] = {}
    for item in options or ():
        try:
            name = str(item[0])
        except (TypeError, IndexError):
            continue
        try:
            want = float(item[1])
        except (TypeError, IndexError, ValueError):
            want = 0.0
        if name in mil_set:
            military[name] = want
        elif name in found_set:
            founder[name] = want
        else:
            domestic[name] = want
    return military, domestic, founder


def advisors(military, domestic, founder):
    """Три советника каркаса: каждый — вызываемый, отдающий своё ведомство.

    Каркас зовёт советника как `fn(rec)`; ведомства уже посчитаны по имени, поэтому тела
    замыканий только отдают словарь — пересчёта нет, и повторный вызов не меняет числа.
    """
    return {
        "military": lambda rec: dict(military),
        "domestic": lambda rec: dict(domestic),
        "founder": lambda rec: dict(founder),
    }


def choose_from_options(options, rec, *, military_names=(), founder_names=FOUNDER_NAMES,
                        rand_value: int = 0):
    """Один вызов каркаса по готовому списку вариантов: `(имя, желание)` или `(None, 0.0)`."""
    from brain.ai_default.build_choice import choose_build
    mil, dom, found = split_options(options, military_names=military_names,
                                    founder_names=founder_names)
    return choose_build(rec, advisors(mil, dom, found), rand_value=rand_value)
