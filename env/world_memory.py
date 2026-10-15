"""ПАМЯТЬ О КАРТЕ — наш `tile_get_known` (у него это `tile_get_known`, §13.359).

Зачем. Стенд отдаёт ТОЛЬКО видимые СЕЙЧАС клетки: на первом ходу террейн «пусто» (255) на 4035
из 4056 клеток, слой `status` вне обзора на тех же клетках, выход ненулевой лишь у 9-21 клетки.
У встроенного ИИ память о виденном есть внутри сервера (`tile_get_known`), и площадки он
перебирает по ВСЕМ когда-либо увиденным клеткам. У нас такой памяти не было: поиск площадок шёл
по 9-21 видимой клетке, после первого города законных мест там не оставалось — отсюда «городов 1-2
и ни одного третьего».

Здесь память просто набирается из наблюдений: что увидели хоть раз — помним (террейн и экстры
клетки, именами). Это не выдумка и не «доступ к чужому»: это те же данные мира, прочитанные в
прошлые ходы.
"""

from __future__ import annotations

from typing import Any

#: клетка → (террейн, экстры) — то, что уже видели.
_KNOWN: dict[tuple[int, int], tuple[str, tuple[str, ...]]] = {}

#: Прибор: сколько раз обновляли и сколько клеток помним (видно в следе).
CALLS: dict[str, int] = {"updates": 0, "tiles": 0, "live": 0}


def update(map_obs: dict[str, Any]) -> int:
    """Запомнить, что видно СЕЙЧАС. Возвращает число известных клеток.

    Пустые клетки текущего наблюдения НЕ запоминаются (иначе «пусто» стало бы знанием),
    но и НЕ стирают уже запомненное.
    """
    if not isinstance(map_obs, dict):
        return len(_KNOWN)
    terrain = map_obs.get("terrain")
    shape = getattr(terrain, "shape", None)
    if shape is None:
        return len(_KNOWN)
    try:
        # Только ЖИВОЕ наблюдение: обёртка `tile_terrain_extras` сама подставляет память,
        # и тогда счётчик «видимых сейчас» стал бы равен всей памяти.
        from env.terrain_work import _live_terrain_extras as tile_terrain_extras
    except Exception:  # noqa: BLE001
        return len(_KNOWN)
    width, height = int(shape[0]), int(shape[1])
    live = 0
    for x in range(width):
        for y in range(height):
            name, extras = tile_terrain_extras(map_obs, x, y)
            if not name or name == "?" or str(name).startswith("?"):
                continue            # пусто сейчас — не знание
            live += 1
            _KNOWN[(int(x), int(y))] = (str(name), tuple(extras or ()))
    CALLS["updates"] += 1
    CALLS["live"] = live
    CALLS["tiles"] = len(_KNOWN)
    return len(_KNOWN)


def learn_full_map(terrain_by_xy: dict[tuple[int, int], str]) -> int:
    """Запомнить ВСЮ карту (из сейва сервера) — то же, что видит его `omniscience`."""
    if not isinstance(terrain_by_xy, dict):
        return len(_KNOWN)
    learned = 0
    for (x, y), name in terrain_by_xy.items():
        if not name:
            continue
        key = (int(x), int(y))
        if _KNOWN.get(key, (None, ()))[0] != str(name):
            learned += 1
        _KNOWN[key] = (str(name), tuple(_KNOWN.get(key, ('', ()))[1]))
    CALLS["full"] = CALLS.get("full", 0) + 1
    CALLS["tiles"] = len(_KNOWN)
    return len(_KNOWN)


def known() -> set[tuple[int, int]]:
    """Клетки, которые мы видели хоть раз."""
    return set(_KNOWN)


def tile(x: int, y: int):
    """Помним ли террейн клетки: `(террейн, экстры)` или None."""
    return _KNOWN.get((int(x), int(y)))


def reset() -> None:
    """Новая партия — новая память."""
    _KNOWN.clear()
    CALLS["updates"] = 0
    CALLS["tiles"] = 0
    CALLS["live"] = 0
