"""Цена работы по клетке: измеренное берём как было, незнание заполняем числами ПРАВИЛ МИРА.

§13.256-13.257: работа предлагается стендом, но оценивается нулём, потому что таблица измеренных
эффектов пуста, а без эффекта выгода работы неизвестна. Владелец: числа из правил мира (и из кода
встроенного ИИ) — тоже наблюдение, их можно прочитать один раз и хранить в картине мира.

Порядок источников:
1. `MEASURED_EXTRA_EFFECTS` — измерено на стенде НАМИ: приоритет, потому что это наши данные;
2. `env/terrain_work_effects.py` — правила мира (`terrain.ruleset`), читаются скриптом;
3. ничего — ноль, как и раньше (догадок не подставляем).
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path("/home/hermes/projects/AI/DOF-MODEL-CIV")
SRC = ROOT / "env" / "terrain_work.py"
src = SRC.read_text(encoding="utf-8")

OLD_DOC = '''Правила здесь НЕ берутся из документации. Эффект работы измеряется на живом
стенде (скрипты `scripts/measure_terrain_effect.py` и
`scripts/inspect_terrain_live.py`): это выход клетки с поставленной экстрой минус
выход того же террейна без неё. Таблица измеренных эффектов живёт в
`env/config.py` (`MEASURED_EXTRA_EFFECTS`) и попадает в формулы через снимок
модели; не измеренный эффект даёт дельту 0, а не правдоподобное число.'''

NEW_DOC = '''Источников два, и порядок между ними важен:

1. **Измерено нами** на живом стенде — `scripts/measure_terrain_effect.py` и
   `scripts/inspect_terrain_live.py`: выход клетки с поставленной экстрой минус выход того же
   террейна без неё. Таблица живёт в `env/config.py` (`MEASURED_EXTRA_EFFECTS`).
2. **Правила мира** — `env/terrain_work_effects.py`, прочитаны из `classic/terrain.ruleset`
   скриптом `scripts/read_terrain_work_effects.py`. Владелец (2026-10-12): числа из правил мира
   и из кода встроенного ИИ — тоже наблюдение, их достаточно узнать один раз и хранить в картине
   мира. Именно этим заполняется незнание, из-за которого цена работы была ровно нулём (§13.257).

Чего нет ни там, ни там — ноль, а не правдоподобное число.'''

assert OLD_DOC in src, "описание источников не найдено"
src = src.replace(OLD_DOC, NEW_DOC, 1)

OLD_IMPORT = '''from typing import Any, Optional'''
NEW_IMPORT = '''from typing import Any, Optional

from .terrain_work_effects import ROAD_EFFECTS, TERRAIN_WORK_EFFECTS'''
assert OLD_IMPORT in src, "место импорта не найдено"
src = src.replace(OLD_IMPORT, NEW_IMPORT, 1)

OLD_EFFECT = '''def tile_effect(extra: str, terrain: str, extras: tuple[str, ...],
                vals: dict[str, Any]) -> Optional[tuple[float, float, float]]:
    """Измеренный эффект экстры на клетке: Δ(еда, щиты, торговля) или None.

    Эффект ищется сначала по паре (экстра, террейн), затем по одной экстре —
    если измерение делалось без привязки к террейну. `None` означает «не
    измерено»: вызывающий код обязан вернуть 0, а не подставить догадку.
    """
    if extra in extras:
        return (0.0, 0.0, 0.0)  # уже стоит: работа ничего не изменит
    table = vals.get("MEASURED_EXTRA_EFFECTS") or {}
    for key in (f"{extra}@{terrain}", extra):
        value = table.get(key)
        if value is not None:
            return tuple(float(v) for v in value)  # type: ignore[return-value]
    return None'''

NEW_EFFECT = '''def world_effect(extra: str, terrain: str) -> Optional[tuple[float, float, float]]:
    """Эффект работы по ПРАВИЛАМ МИРА (`terrain.ruleset`) или None.

    Ирригация и шахта — приросты, записанные у террейна (`irrigation_food_incr`,
    `mining_shield_incr`, …). Дорога и железная дорога — собственные приросты экстры,
    умноженные на процент, который террейн применяет (`road_trade_incr_pct` и родственные).

    Ничего не выдумывается: нет поля в правилах — нет числа.
    """
    row = TERRAIN_WORK_EFFECTS.get(str(terrain)) or {}
    if extra == "Irrigation":
        return (row.get("irrigation_food_incr", 0.0), row.get("irrigation_shield_incr", 0.0),
                row.get("irrigation_trade_incr", 0.0))
    if extra == "Mine":
        return (row.get("mining_food_incr", 0.0), row.get("mining_shield_incr", 0.0),
                row.get("mining_trade_incr", 0.0))
    if extra in ("Road", "Railroad"):
        own = ROAD_EFFECTS.get(extra) or {}
        if not own:
            # В правилах у этой экстры своих приростов нет — тогда и добавить нечего.
            return (0.0, 0.0, 0.0)
        pct = row.get("road_food_incr_pct", 0.0) / 100.0
        pct_shield = row.get("road_shield_incr_pct", 0.0) / 100.0
        pct_trade = row.get("road_trade_incr_pct", 0.0) / 100.0
        return (own.get("food_incr", 0.0) * pct, own.get("shield_incr", 0.0) * pct_shield,
                own.get("trade_incr", 0.0) * pct_trade)
    return None


def tile_effect(extra: str, terrain: str, extras: tuple[str, ...],
                vals: dict[str, Any],
                source: Optional[list[str]] = None) -> Optional[tuple[float, float, float]]:
    """Эффект экстры на клетке: Δ(еда, щиты, торговля) или None.

    Сперва своё измерение (по паре «экстра@террейн», затем по одной экстре), затем ПРАВИЛА МИРА
    (§13.257 — иначе цена работы остаётся нулём). `None` означает «не знаем»: вызывающий код
    обязан вернуть 0, а не подставить догадку. `source` — необязательный список, куда пишется,
    откуда взято число (`измерено` или `правила мира`), чтобы решение было проверяемым.
    """
    if extra in extras:
        if source is not None:
            source.append("уже стоит")
        return (0.0, 0.0, 0.0)  # уже стоит: работа ничего не изменит
    table = vals.get("MEASURED_EXTRA_EFFECTS") or {}
    for key in (f"{extra}@{terrain}", extra):
        value = table.get(key)
        if value is not None:
            if source is not None:
                source.append("измерено")
            return tuple(float(v) for v in value)  # type: ignore[return-value]
    world = world_effect(extra, terrain)
    if world is not None:
        if source is not None:
            source.append("правила мира")
        return world
    return None'''

assert OLD_EFFECT in src, "функция tile_effect не найдена в ожидаемом виде"
src = src.replace(OLD_EFFECT, NEW_EFFECT, 1)
SRC.write_text(src, encoding="utf-8")
print("tile_effect: добавлен источник «правила мира», источник помечается")
