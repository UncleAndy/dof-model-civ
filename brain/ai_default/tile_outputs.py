"""Выходы клетки по правилам мира — основа плюс эффекты улучшений (§13.291).

Зачем. Перенесённое правило встроенного ИИ оценивает клетку через `city_tile_value`
(`infracache.c:293`), а ему нужны выходы клетки. У нас их взять было неоткуда: запись города
в наблюдении НЕ содержит ни выходов по клеткам, ни распределения горожан (измерено в
13.290), а нули `map.output` отозваны как слепые. Поэтому выходы клетки собираются из
правил мира — того же источника, что и всё остальное:

* **основа** — `env.terrain_work_times.TERRAIN_BASE_OUTPUTS` (`grassland (2,0,0)`, …);
* **эффект улучшения** — `env.terrain_work_effects.TERRAIN_WORK_EFFECTS` по приросту,
  который назван в правилах для этого террейна (`irrigation_food_incr`,
  `mining_shield_incr`);
* **дорога** — собственный прирост экстры (`ROAD_EFFECTS`) в доле, заданной террейном
  (`road_trade_incr_pct`).

Имена экстр — те же, что приходят в слое `extras` наблюдения (`Irrigation`, `Mine`, `Road`,
`Railroad`, `River`). Незнакомое имя экстры молча НЕ добавляет ничего: «неизвестно» не
должно выглядеть как «даёт прирост».
"""

from __future__ import annotations

from env.terrain_work_effects import ROAD_EFFECTS, TERRAIN_WORK_EFFECTS
from env.terrain_work_times import TERRAIN_BASE_OUTPUTS

#: Экстра → (поле правил в террейне, индекс статьи выходов `(еда, щиты, торговля)`).
EXTRA_RULE_FIELDS: dict[str, tuple[str, int]] = {
    "Irrigation": ("irrigation_food_incr", 0),
    "Farmland": ("irrigation_food_incr", 0),
    "Mine": ("mining_shield_incr", 1),
}

#: Экстра дорожного рода → ключ в `ROAD_EFFECTS`; доля берётся из террейна.
ROAD_EXTRAS: dict[str, str] = {
    "Road": "road",
    "Railroad": "railroad",
    "River": "river",
}

#: Террейн → ключ процента дороги, которым террейн задаёт долю прироста дороги.
ROAD_PCT_KEY = {
    "road": "road_trade_incr_pct",
    "railroad": "road_shield_incr_pct",
    "river": "road_trade_incr_pct",
}

_INDEX_BY_STAT = {"trade": 2, "shield": 1, "food": 0}


def tile_outputs_from_rules(terrain: str, extras=()) -> tuple[float, float, float] | None:
    """Выходы клетки по правилам мира: `(еда, щиты, торговля)` или None, если террейн неизвестен.

    None, а не нули: неизвестный террейн нельзя выдавать за клетку без выходов — это была бы
    та же слепая подстановка нуля, которую мы отозвали.
    """
    key = str(terrain or "").strip().lower().replace(" ", "_")
    base = TERRAIN_BASE_OUTPUTS.get(key)
    if base is None:
        return None
    food, shield, trade = float(base[0]), float(base[1]), float(base[2])
    effects = TERRAIN_WORK_EFFECTS.get(key, {}) or {}
    present = {str(e) for e in (extras or ())}

    for extra, (field, index) in EXTRA_RULE_FIELDS.items():
        if extra not in present:
            continue
        delta = float(effects.get(field, 0.0) or 0.0)
        if index == 0:
            food += delta
        elif index == 1:
            shield += delta

    for extra, road_key in ROAD_EXTRAS.items():
        if extra not in present:
            continue
        own = ROAD_EFFECTS.get(road_key, {}) or {}
        pct = float(effects.get(ROAD_PCT_KEY[road_key], 0.0) or 0.0)
        for stat_key, own_value in own.items():
            stat = stat_key.replace("_incr", "").replace("_incr_const", "").replace("_bonus", "")
            index = _INDEX_BY_STAT.get(stat)
            if index is None:
                continue
            # Доля, заданная террейном: 0 в правилах означает «дорога здесь ничего не даёт».
            gain = float(own_value) * (pct / 100.0)
            if index == 0:
                food += gain
            elif index == 1:
                shield += gain
            else:
                trade += gain
    return (food, shield, trade)
