"""ХОТЕЛКА ВОЙСКА — буквальный перенос из кода встроенного ИИ (§13.365).

Источник: `ai/default/daimilitary.c` (закреплённый коммит
`14b7a645a74155d4f3dd300221c5b4f0ffca8fe8`):

* `dai_unit_defense_desirability:975-1004` — «насколько нам нужен этот юнит в обороне города»;
* `Greg's algorithm :101-127` — «насколько нужен юнит против КОНКРЕТНОГО нападающего»;
* `dai_process_defender_want:1047+` — сборка хотелки города от опасности (`danger + extra_want`),
  с ролями `L_DEFEND_GOOD`/`L_DEFEND_OK` и правилом `UTYF_FIELDUNIT`.

Почему переносим. Наш выбор производства сравнивал НАШУ меру (`type_price`: ценность с
дисконтом на срок, за щит), а он сравнивает ХОТЕЛКИ своих советников в своей шкале
(`daidomestic.c:489-620` + `adv_better_choice`). Из-за этого его правило «город хочет
основателя настолько, насколько ценна площадка» у нас перебивалось ценой воина
(§13.360: `Settlers 3.8125` против `Warriors 4.5625`).

Что здесь есть и чего ещё нет (честно). Здесь — обе части, дающие ЧИСЛО желания юнита
(оборона и против-нападающего) и приведение к хотелке города от опасности. Ещё НЕ перенесена
последняя часть `dai_process_defender_want` (`:1105-1170`): ветка `can_city_build_unit_now`
с `build_cost`, `limit_cost = shield_stock + 40` и срочностью. Она — следующий шаг, и до неё
`defender_want` возвращает только возведённое в квадрат желание (как в его коде перед этой веткой).
"""

from __future__ import annotations

#: `POWER_DIVIDER` — его константа (`ai/default/daimilitary.c`, `common/aicore/…`).
POWER_DIVIDER = 20

#: Его ветка для не-`GOOD` защитников: `desire /= 2`.
NOT_GOOD_PENALTY = 2

#: Его ветка `UTYF_FIELDUNIT` при нулевой опасности: `desire = -50`.
FIELDUNIT_PEACE_WANT = -50

#: Его ветка `UTYF_GAMELOSS`: `desire /= 10`.
GAMELOSS_PENALTY = 10


def _num(value: object, default: float = 0.0) -> float:
    """Число из мира; отсутствующее не выдумываем."""
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def defense_desirability(utype: dict) -> float:
    """`dai_unit_defense_desirability` (`daimilitary.c:975-1004`), буквально.

    `desire = hp * fp * defense + move_rate / SINGLE_MOVE + attack`, затем надбавка
    `maxbonus_pct` (при >100 — `(x+100)/2`), затем штраф `UTYF_GAMELOSS` (`/10`).
    """
    hp = _num(utype.get("hp"))
    fp = _num(utype.get("firepower"), 1.0)
    defense = _num(utype.get("defense_strength"), utype.get("defense"))
    attack = _num(utype.get("attack_strength"), utype.get("attack"))
    move_rate = _num(utype.get("move_rate"))
    single_move = _num(utype.get("move_fragments"), 3.0) or 3.0  # SINGLE_MOVE
    if str(utype.get("bad_city_defender") or "").upper() in ("TRUE", "1"):
        fp = min(fp, _num(utype.get("low_firepower_pearl_harbour"), fp))
    if str(utype.get("low_firepower") or "").upper() in ("TRUE", "1"):
        fp = min(fp, _num(utype.get("low_firepower_combat_bonus"), fp))
    desire = hp * fp * defense
    desire += move_rate / single_move
    desire += attack
    maxbonus_pct = _num(utype.get("max_defense_mp_bonus_pct"))
    if maxbonus_pct > 100:
        maxbonus_pct = (maxbonus_pct + 100) / 2.0
    desire += desire * maxbonus_pct / 100.0
    if str(utype.get("gameloss") or "").upper() in ("TRUE", "1"):
        desire /= GAMELOSS_PENALTY
    return float(desire)


def attacker_want(defender: dict, attacker: dict) -> float:
    """`Greg's algorithm` (`daimilitary.c:101-127`), буквально.

    `loss = defense * hp * fpdef / (attack * fpatt)`,
    `want = (loss + MAX(0, loss - attacker.hp)) / cost`.

    `defense`/`attack` — силы виртуального защитника против нападающего
    (`get_total_defense_power` / `get_total_attack_power`); их даёт вызывающий, потому что
    сила зависит не только от типа юнита, но и от места и нападающего (местность, бонусы).
    """
    cost = _num(defender.get("build_cost"), 1.0) or 1.0
    loss = (_num(defender.get("total_defense"), _num(defender.get("defense_strength")))
            * _num(defender.get("hp"))
            * _num(defender.get("fpdef"), _num(defender.get("firepower"), 1.0))
            / max(1e-9, _num(defender.get("total_attack"), _num(defender.get("attack_strength")))
                  * _num(defender.get("fpatt"), _num(attacker.get("firepower"), 1.0))))
    attacker_hp = _num(attacker.get("hp"))
    return float((loss + max(0.0, loss - attacker_hp)) / cost)


def defender_want(utype: dict, danger: float, extra_want: float = 0.0,
                  defend_good: bool | None = None,
                  fieldunit: bool | None = None) -> float:
    """`dai_process_defender_want` (`daimilitary.c:1047-1110`), до ветки `can_city_build_unit_now`.

    Порядок его кода: только защитные роли (`L_DEFEND_GOOD`/`L_DEFEND_OK`) → желание обороны →
    `/2` для не-`GOOD` → правило `UTYF_FIELDUNIT` (в мире `-50`, иначе `/2`) → `/POWER_DIVIDER/2`
    → возведение в квадрат. `total_want = danger + extra_want` он считает там же, поэтому
    возвращаем пару (хотелка города, возведённое желание) — как две величины его кода.
    """
    good = utype.get("defend_good") if defend_good is None else defend_good
    ok = utype.get("defend_ok")
    if not good and not ok:
        return 0.0
    desire = defense_desirability(utype)
    if not good:
        desire /= NOT_GOOD_PENALTY
    is_field = utype.get("fieldunit") if fieldunit is None else fieldunit
    if is_field:
        if _num(danger) == 0:
            desire = float(FIELDUNIT_PEACE_WANT)
        else:
            desire /= 2.0
    if desire > 0:
        desire /= POWER_DIVIDER / 2  # его строка: желание на 10
        desire *= desire
    return float(desire)


def city_military_want(utype: dict, danger: float, extra_want: float = 0.0, **kw) -> float:
    """Хотелка города на войско: `total_want = danger + extra_want` плюс желание юнита."""
    return float(_num(danger) + _num(extra_want) + defender_want(utype, danger, extra_want, **kw))
