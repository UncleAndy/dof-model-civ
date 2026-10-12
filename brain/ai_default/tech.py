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
        buildings = tuple(tech or ())
    indices = [i for i in (improvement_index(model, b) for b in buildings) if i is not None]
    if not indices:
        return city_want(city_obs, **kwargs)
    with_extra = dict(city_obs)
    flags = list(with_extra.get("improvements") or [])
    for idx in indices:
        while len(flags) <= idx:
            flags.append(0)
        flags[idx] = 1
    with_extra["improvements"] = flags
    return city_want(with_extra, **kwargs)


__all__ = ["TECH_WANT_FACTOR", "tech_want", "tech_want_total", "unlocked_by",
           "improvement_index", "city_want_with"]