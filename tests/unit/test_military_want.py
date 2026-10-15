"""Сторожа §13.365: хотелка войска по формулам встроенного ИИ (`daimilitary.c`)."""

from __future__ import annotations


def test_defense_desirability_is_his_formula():
    """`hp * fp * defense + move/3 + attack`, затем надбавка бонуса защиты."""
    from brain.ai_default.military_want import defense_desirability
    utype = {"hp": 2, "firepower": 1, "defense_strength": 1, "attack_strength": 1,
             "move_rate": 3, "move_fragments": 3, "max_defense_mp_bonus_pct": 0}
    # 2*1*1 + 3/3 + 1 = 4
    assert defense_desirability(utype) == 4.0
    utype["max_defense_mp_bonus_pct"] = 50
    # 4 + 4*50/100 = 6
    assert defense_desirability(utype) == 6.0


def test_defense_desirability_gameloss_and_high_bonus():
    from brain.ai_default.military_want import defense_desirability
    utype = {"hp": 2, "firepower": 1, "defense_strength": 1, "attack_strength": 1,
             "move_rate": 3, "max_defense_mp_bonus_pct": 200}
    # бонус >100 → (200+100)/2 = 150 %: 4 + 4*150/100 = 10
    assert defense_desirability(utype) == 10.0
    utype["gameloss"] = "TRUE"
    # /10
    assert defense_desirability(utype) == 1.0


def test_attacker_want_is_gregs_algorithm():
    from brain.ai_default.military_want import attacker_want
    defender = {"total_defense": 2, "hp": 2, "fpdef": 1, "total_attack": 1,
                "fpatt": 1, "build_cost": 10}
    attacker = {"hp": 2, "firepower": 1}
    # loss = 2*2*1/(1*1) = 4; want = (4 + max(0, 4-2))/10 = 0.6
    assert abs(attacker_want(defender, attacker) - 0.6) < 1e-9


def test_defender_want_roles_and_fieldunit():
    from brain.ai_default.military_want import defender_want
    ok_only = {"hp": 1, "firepower": 1, "defense_strength": 1, "attack_strength": 0,
               "move_rate": 3, "defend_ok": True}
    good = dict(ok_only, defend_good=True)
    # не GOOD: желание 2 → /2 = 1 → /10 → 0.01... затем в квадрат: 0.0001
    assert abs(defender_want(ok_only, danger=5) - (2 / 2 / (20 / 2)) ** 2) < 1e-9
    # GOOD: 2 → /10 = 0.2 → 0.04
    assert abs(defender_want(good, danger=5) - (2 / (20 / 2)) ** 2) < 1e-9
    # без защитных ролей не рассматривается вовсе
    assert defender_want({"hp": 8}, danger=5) == 0.0
    # полевое в мирное время — его -50 (в квадрат не возводится, желание не положительное)
    assert defender_want(dict(good, fieldunit=True), danger=0) == -50.0
    # в опасность — делится пополам
    assert abs(defender_want(dict(good, fieldunit=True), danger=5) - (1.0 / 10) ** 2) < 1e-9


def test_city_military_want_adds_danger():
    from brain.ai_default.military_want import city_military_want
    good = {"hp": 2, "firepower": 1, "defense_strength": 1, "attack_strength": 1,
            "move_rate": 3, "defend_good": True}
    danger = 12.0
    assert abs(city_military_want(good, danger) - (danger + (4 / 10) ** 2)) < 1e-9
