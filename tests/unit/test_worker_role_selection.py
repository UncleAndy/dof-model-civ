"""Terrain-work capability comes from the live action offer, not unit names."""

from brain.forecast import live


def test_founders_are_not_preempted_by_the_separate_worker_choice():
    select = getattr(live, "_terrain_work_unit_ids", None)
    assert select is not None, "worker candidates must use the server's offered work actions"

    units = {
        "unit_10": {"owner": 1, "type_rule_name": "Settlers", "pop_cost": 1},
        "unit_11": {"owner": 1, "type_rule_name": "Warriors"},
        "unit_12": {"owner": 2, "type_rule_name": "Settlers", "pop_cost": 1},
        "unit_13": {"owner": 1, "type_rule_name": "Workers"},
    }
    offered = {
        10: {"mine": {"enabled": True}},
        11: {"goto_1": {"enabled": True}},
        12: {"irrigate": {"enabled": True}},
        "13": {"build_road": {"enabled": True}},
    }

    assert select(units, offered, 1, ("mine", "irrigate", "build_road")) == (
        "unit_13",
    )
