"""Оценка технологии — правило встроенного ИИ, не наше.

Источник: `ai/default/daitech.c` (`dai_tech_base_want`, `dai_tech_effect_values`).
Встроенный ИИ оценивает технологию по ПРИРОСТУ того, что могут его города: он мысленно
выдаёт себе технологию (`research_invention_set(..., TECH_KNOWN)`), заново считает оценку
города (`dai_city_want`) и берёт разницу. К разнице добавляются эффекты, которые эта
технология включает, и всё умножается на ЕГО коэффициент перевода:

    tech_want = v * 14 / 8        (daitech.c: «Same conversion factor as in ...»)

Затем вклады по городам складываются: `aip->tech_want[advance] += tech_want`.

Для нас правило переносится дословно: наша оценка города — `city_options`, прирост она
даёт прямо. Связь «технология → что она открывает» — из правил мира
(`env/rules_ai_prereqs.py`, сгенерирован из `buildings.ruleset`/`units.ruleset`).
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

#: Коэффициент перевода встроенного ИИ (`daitech.c`, у вычисления `tech_want`).
TECH_WANT_FACTOR: float = 14.0 / 8.0


def tech_want(before: float, after: float) -> float:
    """Вклад одного города: разница его оценки, умноженная на коэффициент ИИ."""
    return (after - before) * TECH_WANT_FACTOR


def tech_want_total(before_after: Iterable[tuple[float, float]]) -> float:
    """Сумма вкладов по городам — как `aip->tech_want[...] += tech_want` у него."""
    return sum(tech_want(b, a) for b, a in before_after)


def unlocked_by(tech: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Что открывает технология по правилам мира: (постройки, юниты).

    Имена — как в правилах (`building_granary`, `unit_phalanx`): это сырые имена мира,
    подменять их нельзя. Сопоставление с именами из фактов делает `improvement_index`.
    """
    from env.rules_ai_prereqs import TECH_BUILDINGS, TECH_UNITS
    return (tuple(TECH_BUILDINGS.get(tech, ())), tuple(TECH_UNITS.get(tech, ())))


def _norm(name: Any) -> str:
    """Сравнивать имена построек без учёта вида и регистра: `building_granary` == `Granary`.

    Стенд отдаёт `sup_improvements` и паспортами тоже: списком записей, а не строк. У записи
    берётся её `name`; если имени в ней нет, вернуть пустое — такое сопоставление невозможно,
    а выдумывать его нельзя.
    """
    if isinstance(name, Mapping):
        name = name.get("name") or name.get("rule_name") or ""
    if not isinstance(name, str):
        return ""
    norm = name.strip().lower().replace(" ", "_").replace("-", "_")
    for prefix in ("building_", "unit_", "improvement_"):
        if norm.startswith(prefix):
            norm = norm[len(prefix):]
    return norm


def improvement_index(model: Any, name: str) -> int | None:
    """Номер постройки по её имени — из фактов мира (`improvement.<i>.name`)."""
    try:
        vals = model.values()
    except AttributeError:
        return None
    wanted = _norm(name)
    for key, value in vals.items():
        if not (key.startswith("improvement.") and key.endswith(".name")):
            continue
        if not value or _norm(str(value)) != wanted:
            continue
        try:
            return int(key.split(".")[1])
        except (IndexError, ValueError):
            return None
    return None


def city_want_with(city_want: Callable[..., float], city_obs: dict[str, Any], tech: Any,
                   *, model: Any = None, **kwargs) -> float:
    """Оценка города, если бы технология уже была известна.

    Единственное, что видно нашей мере от технологии, — открытые ею ПОСТРОЙКИ: они
    добавляются к списку уже стоящих в городе, и оценка пересчитывается. Это и есть
    подстановка «выдать себе технологию и посмотреть на прирост», только средствами
    нашей меры, без новых коэффициентов. Постройка без номера в фактах мира просто
    пропускается — выдумывать ей номер нельзя.

    `tech` — либо имя технологии, либо готовый перечень открываемых построек (стенд отдаёт
    его сам полем `sup_improvements`; этот путь точнее, потому что это данные мира).
    """
    if isinstance(tech, str):
        buildings, _ = unlocked_by(tech)
    else:
        buildings = tuple(tech) if tech is not None and not isinstance(tech, str) else ()
    indices = [i for i in (improvement_index(model, b) for b in buildings) if i is not None]
    if not indices:
        return city_want(city_obs, **kwargs)
    with_extra = dict(city_obs)
    # В живом потоке `improvements` — массив numpy, а не список: проверка на истинность
    # у него неопределена и валит прогон (`ValueError: truth value ... is ambiguous`).
    # Проверка была написана так, что этого не видно на списках, — теперь видно.
    raw_flags = with_extra.get("improvements")
    flags = [] if raw_flags is None else list(raw_flags)
    for idx in indices:
        while len(flags) <= idx:
            flags.append(0)
        flags[idx] = 1
    with_extra["improvements"] = flags
    return city_want(with_extra, **kwargs)


def best_of(values: Mapping[str, float]) -> str | None:
    """Технология с наибольшим хотением — его `ai_choose_tech` (`daitech.c`).

    Он берёт максимум строгим сравнением (`if (tech_want[a] > best)`), поэтому при РАВЕНСТВЕ
    побеждает та, что встретилась первой, а не случайная. Порядок задаёт мир: словарь
    заполняется в порядке предложения, и переставлять его нельзя — иначе выбор перестанет
    быть повторяемым на одинаковом входе.
    """
    best_name: str | None = None
    best_value: float | None = None
    for name, value in values.items():
        if value is None:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if best_value is None or v > best_value:
            best_name, best_value = str(name), v
    return best_name


def keep_best_tech(cands: list, *, name_of, value_of, family_prefix: str) -> list:
    """Оставить в семье технологии только лучшую по его числу (§13.311).

    Зачем семьёй, а не общим счётом: сравнивать хотение технологии с хотением постановки
    города на одной шкале нельзя — у него это РАЗНЫЕ решения, и общего коэффициента между
    ними он не задаёт. Здесь выбирается ТОЛЬКО то, ЧТО исследовать, а место семьи в общем
    решении остаётся прежним.

    Если его число не посчиталось НИ ДЛЯ ОДНОЙ технологии (нет данных мира — номера построек,
    списка открываемого), семья возвращается нетронутой: действовать по незнанию нельзя,
    это оговорено правилом проекта.
    """
    family = [c for c in cands if str(name_of(c) or "").startswith(family_prefix)]
    if len(family) < 2:
        return cands
    values: dict[str, float] = {}
    for c in family:
        v = value_of(c)
        if v is not None:
            values[str(name_of(c))] = v
    if not values:
        return cands
    best = best_of(values)
    if best is None:
        return cands
    return [c for c in cands
            if not str(name_of(c) or "").startswith(family_prefix)
            or str(name_of(c)) == best]


__all__ = ["TECH_WANT_FACTOR", "tech_want", "tech_want_total", "unlocked_by",
           "improvement_index", "city_want_with", "best_of", "keep_best_tech"]