"""Сторожа §13.376: города из вектора `c={...}` ходового сейва стенда."""

from __future__ import annotations

SAVE = """[player0]
username="me"
name="Me"
ncities=2
c={"y","x","id","name","size","food_stock","shield_stock","currently_building_kind","currently_building_name"}
45,47,123,"Ciudad del Este",1,12,4,"UnitType","Warriors"
}
46,45,122,"Montevideo",1,12,5,"UnitType","Settlers"
u={"id","x","y","homecity"}
109,50,25,0
}
[player1]
username="Unassigned"
c={"y","x","id","name"}
10,10,7,"EnemyTown"
}
"""


def test_vector_is_parsed_by_columns():
    from env.city_vector import parse_city_vectors
    recs = parse_city_vectors(SAVE)
    assert set(recs) == {"123", "122", "7"}
    assert recs["123"]["name"] == "Ciudad del Este"
    assert recs["123"]["y"] == 45 and recs["123"]["x"] == 47
    assert recs["123"]["shield_stock"] == 4
    assert recs["123"]["currently_building_name"] == "Warriors"
    assert recs["122"]["currently_building_name"] == "Settlers"


def test_only_our_player_when_username_given():
    from env.city_vector import parse_city_vectors
    mine = parse_city_vectors(SAVE, username="me")
    assert set(mine) == {"123", "122"}


def test_missing_fields_are_not_invented():
    from env.city_vector import parse_city_vectors
    recs = parse_city_vectors(SAVE, username="me")
    assert "pop_cost" not in recs["123"]
    assert "can_build_unit" not in recs["123"]


def test_units_vector_is_not_read_as_cities():
    from env.city_vector import parse_city_vectors
    recs = parse_city_vectors(SAVE, username="me")
    assert "109" not in recs
