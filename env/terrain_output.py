"""Серверный выход клетки из городских пакетов; map.output — только база.

CityWorkTile.output_idx использует протокольную нумерацию city map, включая
геометрию и края карты. Работаем с уже полученными собственными городскими
пакетами клиента, не запрашиваем скрытое серверное состояние.
"""
from __future__ import annotations

from collections.abc import Mapping
from numbers import Integral


OUTPUT_FIELDS = ("output_food", "output_shield", "output_trade")


def _action_output(action, x: int, y: int) -> tuple[int, int, int] | None:
    tile = getattr(action, "ptile", None)
    packet = getattr(action, "pcity", None)
    index = getattr(action, "output_idx", None)
    if not isinstance(tile, Mapping) or not isinstance(packet, Mapping):
        return None
    if (tile.get("x"), tile.get("y")) != (x, y):
        return None
    if not isinstance(index, Integral) or index < 0:
        return None
    arrays = [packet.get(field) for field in OUTPUT_FIELDS]
    if any(array is None or index >= len(array) for array in arrays):
        return None
    values = tuple(int(array[index]) for array in arrays)
    return values if all(value >= 0 for value in values) else None


def server_tile_outputs(city_actions: Mapping, x: int, y: int) -> dict:
    """Выход одной клетки отдельно по каждому городу; отсутствие — не ноль."""
    result = {}
    for city_id, actions in city_actions.items():
        for action in actions.values():
            output = _action_output(action, x, y)
            if output is not None:
                result[str(city_id)] = output
                break
    return result


def paired_output_deltas(before: Mapping, after: Mapping) -> dict:
    """Сравнить только тот же город; никакого среднего или подстановки нуля."""
    return {city_id: tuple(new - old for old, new in zip(output, after[city_id]))
            for city_id, output in before.items() if city_id in after}
