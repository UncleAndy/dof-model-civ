"""Серверный выход клетки нельзя заменять базовым map.output."""
from types import SimpleNamespace

import pytest

from env import config as cfg
from env.terrain_output import paired_output_deltas, server_tile_outputs


def tile_action(*, city=1, tile=(4, 5), idx=0, outputs=(3, 1, 2)):
    packet = {"id": city, "output_food": [outputs[0]],
              "output_shield": [outputs[1]], "output_trade": [outputs[2]]}
    return SimpleNamespace(pcity=packet, ptile={"x": tile[0], "y": tile[1]},
                           output_idx=idx)


def test_reads_server_arrays_at_the_target_tile():
    actions = {1: {"city_work_0": tile_action()}}
    assert server_tile_outputs(actions, 4, 5) == {"1": (3, 1, 2)}
    assert server_tile_outputs(actions, 5, 4) == {}


def test_missing_sensor_is_unknown_not_zero():
    action = tile_action()
    del action.pcity["output_trade"]
    assert server_tile_outputs({1: {"work": action}}, 4, 5) == {}
    assert server_tile_outputs({}, 4, 5) == {}


@pytest.mark.parametrize("idx", [None, -1, 10])
def test_invalid_city_map_index_is_not_a_measurement(idx):
    assert server_tile_outputs({1: {"work": tile_action(idx=idx)}}, 4, 5) == {}


def test_same_tile_in_different_cities_keeps_context_separate():
    actions = {1: {"work": tile_action()},
               2: {"work": tile_action(city=2, outputs=(2, 1, 2))}}
    assert server_tile_outputs(actions, 4, 5) == {"1": (3, 1, 2), "2": (2, 1, 2)}


def test_zero_server_output_is_valid_data():
    actions = {1: {"work": tile_action(outputs=(0, 0, 0))}}
    assert server_tile_outputs(actions, 4, 5) == {"1": (0, 0, 0)}


def test_pairing_never_compares_different_city_contexts():
    assert paired_output_deltas({"1": (1, 1, 0)}, {"2": (3, 1, 0)}) == {}
    assert paired_output_deltas({"1": (1, 1, 0)}, {"1": (2, 1, 0)}) == {"1": (1, 0, 0)}


def test_base_only_map_measurements_are_not_work_effect_priors():
    for extra in ("Irrigation", "Road"):
        for terrain in ("Grassland", "Plains", "Hills"):
            assert f"{extra}@{terrain}" not in cfg.MEASURED_EXTRA_EFFECTS
