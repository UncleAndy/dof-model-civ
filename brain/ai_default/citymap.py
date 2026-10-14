"""ЕГО РЕЗЕРВ ГОРОДСКИХ МЕСТ — перенос `common/aicore/citymap.c`.

Зачем это перенесено. У него поселенец, выбрав место, ЗАНИМАЕТ его: `citymap_reserve_city_spot`
(`daitools.c:708`) помечает клетку как `-id` и «crowds» её радиус, а `citymap_reserve_tile`
(`daisettler.c:1139`) занимает лучшую рабочую клетку будущего города. Проверка
`city_desirability` (`daisettler.c:701`) отбрасывает площадку, если ЛЮБАЯ клетка в пределах
`citymindist-1` от неё уже занята (`citymap_is_reserved`). У нас этого не было вовсе: поселенцы
сгруживались (пять в углу карты), каждый считал свою клетку лучшей, и город не появлялся.

Числа — его: `CITY_MAP_DEFAULT_RADIUS_SQ = 5` (радиус города), правило занятости —
отрицательное значение, «crowding» — положительное.
"""

from __future__ import annotations

#: ЕГО `CITY_MAP_DEFAULT_RADIUS_SQ` (`common/aicore/citymap.h`).
CITY_MAP_DEFAULT_RADIUS_SQ: int = 5


def _owner_id(uid: object) -> int:
    """Числовой признак владельца: у него это `punit->id`, у нас — тот же id."""
    try:
        return int(uid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return abs(hash(str(uid))) % 100000 + 1


class CityMap:
    """Занятость клеток: `-id` — место под город, `> 0` — «crowded» (в радиусе N городов)."""

    def __init__(self) -> None:
        self._map: dict[tuple[int, int], int] = {}

    @staticmethod
    def _radius(x: int, y: int) -> list[tuple[int, int]]:
        """ЕГО `city_tile_iterate(CITY_MAP_DEFAULT_RADIUS_SQ, …)` — сам центр и его радиус."""
        from brain.ai_default.city_tiles import workable_offsets
        tiles = [(int(x), int(y))]
        tiles += [(int(x) + dx, int(y) + dy)
                  for dx, dy in workable_offsets(CITY_MAP_DEFAULT_RADIUS_SQ)]
        return tiles

    def reserve_city_spot(self, x: int, y: int, uid: object) -> None:
        """`citymap_reserve_city_spot` (`citymap.c:120`).

        Для каждой клетки радиуса: своё прежнее занятие снять, а «crowding» увеличить;
        затем центр помечается как занятый этим владельцем.
        """
        _id = _owner_id(uid)
        for tx, ty in self._radius(x, y):
            cur = self._map.get((tx, ty), 0)
            if cur == -_id:
                cur = 0
                self._map[(tx, ty)] = 0
            if cur >= 0:
                self._map[(tx, ty)] = cur + 1
        self._map[(int(x), int(y))] = -_id

    def free_city_spot(self, x: int, y: int, uid: object) -> None:
        """`citymap_free_city_spot` (`citymap.c:146`): снять занятость и «crowding» радиуса."""
        _id = _owner_id(uid)
        for tx, ty in self._radius(x, y):
            cur = self._map.get((tx, ty), 0)
            if cur == -_id:
                self._map[(tx, ty)] = 0
            elif cur > 0:
                self._map[(tx, ty)] = cur - 1

    def reserve_tile(self, x: int, y: int, uid: object) -> None:
        """`citymap_reserve_tile` (`citymap.c:161`): занять ОДНУ клетку."""
        self._map[(int(x), int(y))] = -_owner_id(uid)

    def is_reserved(self, x: int, y: int) -> bool:
        """`citymap_is_reserved` (`citymap.c:184`): занята ли клетка."""
        return self._map.get((int(x), int(y)), 0) < 0

    def raw(self, x: int, y: int) -> int:
        """Значение карты в клетке — для сторожей и разбора (у него `citymap_read`)."""
        return self._map.get((int(x), int(y)), 0)
