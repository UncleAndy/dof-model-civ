"""Сторожа §13.363: вся карта из сейва сервера (то же, что видит встроенный ИИ)."""

from __future__ import annotations

SAVE = """[game]
turn=6
[map]
have_huts=TRUE
t0000="ggh"
t0001="  +"
[players]
t0002="ggg"
[settings]
fogofwar=FALSE
"""


def test_map_rows_are_parsed_by_row_and_column():
    from env.map_from_save import parse_map_rows
    tiles = parse_map_rows(SAVE)
    assert tiles[(0, 0)] == "Grassland"
    assert tiles[(2, 0)] == "Hills"
    assert tiles[(0, 1)] == "Ocean"
    assert tiles[(2, 1)] == "Lake"
    # строка карты внутри другого раздела не читается
    assert (0, 2) not in tiles


def test_unknown_symbol_is_not_invented():
    from env.map_from_save import parse_map_rows
    tiles = parse_map_rows("[map]\nt0000=\"g?g\"\n")
    assert tiles == {(0, 0): "Grassland", (2, 0): "Grassland"}


def test_learn_full_map_fills_memory_and_revealed_tiles():
    from brain.forecast.live import revealed_tiles
    from env import world_memory

    world_memory.reset()
    assert world_memory.learn_full_map({(1, 1): "Grassland", (2, 1): "Ocean"}) == 2
    assert world_memory.known() == {(1, 1), (2, 1)}
    # наблюдение клиента (§13.361) для невидимой сейчас клетки отдаёт террейн из памяти
    assert world_memory.tile(2, 1) == ("Ocean", ())
    assert revealed_tiles({"terrain": None}) == {(1, 1), (2, 1)}
    world_memory.reset()


def test_memory_is_not_overwritten_by_observation():  # §13.361: «пусто» не стирает знание
    from env import world_memory
    world_memory.reset()
    world_memory.learn_full_map({(5, 5): "Desert"})
    assert world_memory.update({}) == 1
    assert world_memory.tile(5, 5) == ("Desert", ())
    world_memory.reset()
