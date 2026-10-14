"""§13.343: боевой род спрашиваем только при нужде — его правила (`daimilitary.c`).

Сторожа держат три вещи, каждая из которых была ошибкой по отдельности:
1) классификацию «боевой ли род» — по правилам мира, а не по нашим догадкам;
2) опасность считается по ВИДИМЫМ чужим юнитам и его горизонту в 3 хода
   (`assess_turns`), а не «на всякий случай»;
3) ранний отказ советника (щиты <= 0) стоит ВПЕРЕДИ условия нужды, как у него.
"""

from __future__ import annotations

from brain.ai_default import danger as D

NONE = 255


def _grid(size: int, spots: dict[tuple[int, int], int]) -> list[list[int]]:
    g = [[NONE] * size for _ in range(size)]
    for (x, y), owner in spots.items():
        g[x][y] = owner
    return g


def _obs(spots: dict[tuple[int, int], int], *, size: int = 25,
         attack: float = 5.0, move: float = 3.0) -> dict:
    return {
        "tech": {"t": {"sup_units": [{"attack_strength": attack}]}},
        "unit": {"1": {"type_attack_strength": attack, "type_move_rate": move}},
        "map": {"unit_owner": _grid(size, spots)},
    }


CITY = {"id": 121, "x": 5, "y": 5, "prod_shield": 3.0}


def test_military_class_comes_from_world_rules():
    assert D.is_military("Warriors") is True
    assert D.is_military("Settlers") is False


def test_no_visible_enemy_means_no_danger():
    out = D.assess_danger(CITY, _obs({}), my_player_id=0)
    assert out["danger"] == 0.0 and out["units"] == 0
    assert "не видно" in out["note"]


def test_danger_sums_visible_enemies_inside_his_three_turn_horizon():
    # Расстояния Чебышёва 2, 7 и 15 при средней скорости 3 → сроки 1, 3 и 5 ходов.
    # Его горизонт — 3 (`assess_turns`), поэтому третий юнит в сумму НЕ входит.
    obs = _obs({(5, 7): 1, (5, 12): 2, (5, 20): 3})
    out = D.assess_danger(CITY, obs, my_player_id=0)
    assert out["units"] == 3
    assert out["danger"] == 10.0          # 5.0 + 5.0
    assert out["urgency"] == 2 and out["grave"] == 1


def test_early_refusal_stands_before_the_need_condition():
    obs = _obs({(5, 6): 1})               # враг рядом, нужда есть…
    need, why, _ = D.military_need(CITY, obs, 0, shields=0.0)
    assert need is False and "ранний отказ" in why      # …но щитов нет — отказ


def test_enemy_in_reach_opens_the_gate():
    obs = _obs({(5, 6): 1})
    need, why, _ = D.military_need(CITY, obs, 0, shields=3.0)
    assert need is True and "опасность" in why


def test_peace_means_no_military_want():
    need, why, _ = D.military_need(CITY, _obs({}), 0, shields=3.0)
    assert need is False and "войск не просим" in why
