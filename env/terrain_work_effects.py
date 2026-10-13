"""ЭФФЕКТ РАБОТЫ ПО КЛЕТКЕ — прочитан из правил мира, не выдуман.

Источник: `/home/docker/freeciv/share/freeciv/classic/terrain.ruleset` в контейнере `freeciv-web`. Сгенерировано: `scripts/read_terrain_work_effects.py`.

Указание владельца: эффект — характеристика мира, её достаточно узнать один раз.
"""

from __future__ import annotations

#: террейн → приросты, которые даёт работа (только ненулевые поля правил).
TERRAIN_WORK_EFFECTS: dict[str, dict[str, float]] = {
    "desert": {'irrigation_food_incr': 1.0, 'mining_shield_incr': 1.0, 'road_trade_incr_pct': 100.0},
    "glacier": {'mining_shield_incr': 1.0},
    "grassland": {'irrigation_food_incr': 1.0, 'road_trade_incr_pct': 100.0},
    "hills": {'irrigation_food_incr': 1.0, 'mining_shield_incr': 3.0},
    "mountains": {'mining_shield_incr': 1.0},
    "plains": {'irrigation_food_incr': 1.0, 'road_trade_incr_pct': 100.0},
    "tundra": {'irrigation_food_incr': 1.0},
}

#: дорога/железная дорога → собственные приросты экстры.
ROAD_EFFECTS: dict[str, dict[str, float]] = {
    "railroad": {'shield_bonus': 50.0},
    "river": {'trade_incr_const': 1.0},
    "road": {'trade_incr': 1.0},
}

#: террейн → процент применения приростов дороги.
ROAD_PCT_FIELDS = (
    "road_food_incr_pct",
    "road_shield_incr_pct",
    "road_trade_incr_pct",
)

#: экстра работы → поле правил, которым выражен её эффект. Нужно, чтобы «эффект
#: известен» можно было утверждать по ПРАВИЛАМ (единый источник мира), а не по
#: нулю слепого датчика: нули `map.output` отозваны, знание обязано быть настоящим.
WORK_EXTRA_RULE_FIELDS: dict[str, tuple[str, ...]] = {
    "Irrigation": ("irrigation_food_incr",),
    "Mine": ("mining_shield_incr",),
}


def effect_known_from_rules(extra: str) -> bool:
    """Определён ли эффект экстры ПРАВИЛАМИ мира (а не выдуман и не слепой ноль).

    Дорога и её виды описаны собственной секцией `road_*`; ирригация и шахта —
    полями террейна (`irrigation_food_incr`, `mining_shield_incr`). Если ни одной
    записи правила нет, эффект неизвестен — и это честный ответ, а не ноль.
    """
    name = str(extra or "")
    if ROAD_EFFECTS.get(name.lower()):
        return True
    fields = WORK_EXTRA_RULE_FIELDS.get(name)
    if not fields:
        return False
    terrains = TERRAIN_WORK_EFFECTS.values()
    return any(field in spec for field in fields for spec in terrains)
