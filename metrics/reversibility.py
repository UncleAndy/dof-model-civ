"""Обратимость действий CivRealm — правило мира, нужное прибору.

Перенесено из v1 (`env/action_mapper.py`) в v2 как самостоятельный модуль, потому что это
знание о **словаре мира** (какие действия нельзя отменить), а не часть снятой модели. Прибору
оно нужно, чтобы считать `irreversibility_ratio` (вход аксиомы 3/4 DOF-Core) без зависимости
от модели.

Матчинг префиксный: параметризованные имена — `goto_12`, `research_tech_Code of Laws_13`,
`set_sci_lux_tax_0_40_60` — классифицируются как их базовое действие. Неизвестное действие
считается **обратимым**: лучше не переоценить необратимость, чем поставить вето на всё.
"""

from __future__ import annotations

# ── Словарь DOF-SPEC ──────────────────────────────────────────────────────────

#: Действия, которые нельзя отменить.
IRREVERSIBLE_ACTIONS = {
    'declare_war',
    'attack',
    'conquer_city',
    'disband',
    'destroy_improvement',
    'burn_house',
    'pillage',
}

#: Действия, частично обратимы (отменяются ценой потери).
PARTIALLY_REVERSIBLE = {
    'build_city',         # можно распустить, но вложение потеряно
    'build_improvement',  # можно продать, но с потерей золота
    'research_tech',      # можно сменить, накопленные баллы теряются
    'build_unit',         # можно распустить
    'trade_agreement',    # можно расторгнуть
    'alliance',           # можно разорвать
}

#: Полностью обратимые действия.
FULLY_REVERSIBLE = {
    'goto',
    'fortify',
    'sentry',
    'build_road',
    'irrigation',
    'mine',
    'set_tax_rate',
    'set_luxury_rate',
    'set_science_rate',
    'change_government',
    'patrol',
    'trade_gold',
    'trade_tech',
}

# ── Словарь провода (реальные имена CivRealm) ─────────────────────────────────
# Имена, наблюдавшиеся в живых играх, ложатся на множества выше по префиксу. Держим их
# отдельно, чтобы словарь DOF-SPEC оставался целым, а мост понимал настоящий провод.

_REVERSIBLE_PREFIXES = (
    'goto',            # goto_12 — движение можно переиграть
    'fortify',
    'sentry',
    'keep_activity',
    'irrigation',
    'mine',
    'plant',
    'cultivate',
    'transform_terrain',
    'fortress',
    'airbase',
    'road',
    'railroad',
    'set_sci_lux_tax',  # раскладка налог/роскошь/наука, меняется каждый ход
    'change_gov',       # правительство можно вернуть (ценой хода)
    'set_tech_goal',    # цель исследований — совет, меняется свободно
    'chat',             # чистая коммуникация
)

_IRREVERSIBLE_PREFIXES = (
    'disband',
    'attack',
    'pillage',
    'conquer_city',
    'burn_house',
    'destroy_improvement',
    'declare_war',
)

_PARTIALLY_REVERSIBLE_PREFIXES = (
    'found_city',       # поселение не «разосновать» без потери
    'research_tech',    # накопленные баллы теряются при смене
    'build_improvement',
    'build_unit',
    'build_city',
    'alliance',
    'trade_agreement',
)


def classify_reversibility(action_name: str) -> bool:
    """True, если действие обратимо (вход аксиомы 3/4).

    Точный словарь DOF-SPEC проверяется первым, затем префиксы реального словаря CivRealm.
    Неизвестное имя — обратимо: консервативный по умолчанию вариант не ставит лишних вето.
    """
    name = '' if action_name is None else str(action_name)
    base = name.split('_')[0]

    if name in FULLY_REVERSIBLE or base in FULLY_REVERSIBLE:
        return True
    if name in IRREVERSIBLE_ACTIONS or base in IRREVERSIBLE_ACTIONS:
        return False
    if name in PARTIALLY_REVERSIBLE or base in PARTIALLY_REVERSIBLE:
        return False  # частичная обратимость для DOF считается необратимостью

    for prefix in _IRREVERSIBLE_PREFIXES:
        if name.startswith(prefix):
            return False
    for prefix in _PARTIALLY_REVERSIBLE_PREFIXES:
        if name.startswith(prefix):
            return False
    for prefix in _REVERSIBLE_PREFIXES:
        if name.startswith(prefix):
            return True

    return True  # неизвестное -> обратимо (не переоцениваем необратимость)