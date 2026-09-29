"""Цена работ на террейне: рабочий поднимает DoF города (пункт 1).

Работа (`irrigation`, `mine`, `build_road`, …) меняет выход клетки, а клетку
обрабатывает город — значит это канал «рабочий → DoF города», и до сих пор он
был оценён нулём, то есть невидим для ядра.

Правила здесь НЕ берутся из документации. Эффект работы измеряется на живом
стенде (скрипты `scripts/measure_terrain_effect.py` и
`scripts/inspect_terrain_live.py`): это выход клетки с поставленной экстрой минус
выход того же террейна без неё. Таблица измеренных эффектов живёт в
`env/config.py` (`MEASURED_EXTRA_EFFECTS`) и попадает в формулы через снимок
модели; не измеренный эффект даёт дельту 0, а не правдоподобное число.

Отдельно: `cultivate`/`plant`/`transform_terrain` меняют САМ террейн (замерено:
Forest+Pheasant ⇄ Swamp за 4 хода), поэтому в таблицу экстр они не входят — их
эффект зависит от террейна-результата и остаётся неоценённым до отдельного замера.
"""
from __future__ import annotations

from typing import Any, Optional

#: Работа CivRealm → экстра, которую она ставит на клетку.
WORK_ACTION_EXTRA: dict[str, str] = {
    "irrigation": "Irrigation",
    "irrigate": "Irrigation",
    "mine": "Mine",
    "build_road": "Road",
    "road": "Road",
    "railroad": "Railroad",
    "farmland": "Farmland",
}

#: Работы, меняющие сам террейн: их цена — не «экстра», а смена типа (пока не
#: оценена; замерено только время: 4 хода, и цикл Forest ⇄ Swamp).
TERRAIN_TRANSFORM_ACTIONS: tuple[str, ...] = ("cultivate", "plant", "transform_terrain")

#: Время работ по замерам: `cultivate` (Forest ⇄ Swamp) — 4 хода; `irrigation`
#: на равнине — 3 хода. Значение ниже — верхняя из наблюдённых длительностей;
#: пока оно нигде не дисконтирует цену (работа оплачивается один раз, а выгода
#: считается по факту улучшения), но фиксирует порядок величины.
MEASURED_WORK_TURNS: int = 4


def work_extra(action_name: str) -> Optional[str]:
    """Экстра, которую ставит работа, либо None (это не работа над клеткой)."""
    name = str(action_name or "")
    for prefix in sorted(WORK_ACTION_EXTRA, key=len, reverse=True):
        if name.startswith(prefix):
            return WORK_ACTION_EXTRA[prefix]
    return None


def is_terrain_transform(action_name: str) -> bool:
    name = str(action_name or "")
    return any(name.startswith(p) for p in TERRAIN_TRANSFORM_ACTIONS)


def terrain_names() -> tuple[list[str], list[str]]:
    """Имена террейнов и экстр из civrealm (при недоступности — пустые списки)."""
    try:
        from civrealm.freeciv.map.map_const import EXTRA_NAMES, TERRAIN_NAMES

        return list(TERRAIN_NAMES), list(EXTRA_NAMES)
    except Exception:  # pragma: no cover - civrealm недоступен
        return [], []


def tile_terrain_extras(map_obs: dict[str, Any], x: int, y: int) -> tuple[str, tuple[str, ...]]:
    """Террейн и экстры клетки — именами (для ключа измеренной таблицы)."""
    terrain_names_, extra_names = terrain_names()
    terrain_layer = (map_obs or {}).get("terrain")
    extras_layer = (map_obs or {}).get("extras")
    if terrain_layer is None:
        return "?", ()
    try:
        import numpy as np

        ta = np.asarray(terrain_layer)
        xa, ya = ta.shape[0], ta.shape[1]
        if not 0 <= y < ya:
            return "?", ()          # за краем карты (полюс): клетки нет
        tid = int(ta[x % xa][y])     # X: карта — цилиндр
    except Exception:  # pragma: no cover
        return "?", ()
    tname = terrain_names_[tid] if tid < len(terrain_names_) else f"?{tid}"
    extras: tuple[str, ...] = ()
    if extras_layer is not None:
        try:
            import numpy as np

            ea = np.asarray(extras_layer)
            if ea.ndim == 3:
                xa, ya = ea.shape[0], ea.shape[1]
                if not 0 <= y < ya:
                    return tname, ()     # за краем карты (полюс)
                cell = ea[x % xa][y]     # X: карта — цилиндр
                extras = tuple(sorted(
                    extra_names[i] if i < len(extra_names) else f"?{i}"
                    for i in range(ea.shape[2]) if cell[i]
                ))
        except Exception:  # pragma: no cover
            extras = ()
    return tname, extras


def tile_effect(extra: str, terrain: str, extras: tuple[str, ...],
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
    return None


def tile_effect_gain(extra: str, terrain: str, extras: tuple[str, ...],
                     vals: dict[str, Any], *, discount: float = 1.0) -> float:
    """Полезность работы в «единицах улучшения» с дисконтом (0 — не измерено)."""
    effect = tile_effect(extra, terrain, extras, vals)
    if effect is None:
        return 0.0
    return discount * (max(0.0, effect[0]) + max(0.0, effect[1]) + max(0.0, effect[2]))
