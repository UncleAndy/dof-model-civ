"""Назначение поселенца: он идёт к лучшей площадке и основывает город по прибытии.

У его ИИ поселенец **НЕ** основывает город там, где стоит. `ai/default/daisettler.c`
(`settler_map_iterate`, строки 800–825) перебирает площадки, считает `city_desirability`
(включая `food_starvation`/`shield_starvation` из `cityresult_fill`) и ведёт юнита к лучшей;
город ставится ПО ДОСТИЖЕНИИ.

У нас не было ни назначения, ни оценки площадки на стороне юнита: основание стояло первым по
приоритету (стратегии: `build_city`/`found_city`), где бы поселенец ни оказался. Город,
основанный на голодной площадке, умирал на 2-м ходу (`Famine destroys … entirely`), сторона
выбывала — измерено (§13.305). Это третья по счёту «половина его правила» за заход.

Модуль переносит недостающее: выбор назначения по ЕГО числам и шаг к нему.

Направления хода — правило клиента, а не наше изобретение: `goto_0..7` = СЗ, С, СВ, З, В, ЮЗ,
Ю, ЮВ (нумерация НЕ круговая), закреплено в памяти проекта.
"""

from __future__ import annotations

import math
import os
from typing import Any, Iterable

#: ЕГО `RESULT_IS_ENOUGH` (`daisettler.c:94`) — «хватит искать дальше» для раннего выхода.
from brain.ai_default.values import RESULT_IS_ENOUGH

#: Направление каждого `goto_*` в координатах (dx, dy). Нумерация не круговая.
GOTO_DIRECTIONS: dict[str, tuple[int, int]] = {
    "goto_0": (-1, -1),   # СЗ
    "goto_1": (0, -1),    # С
    "goto_2": (1, -1),    # СВ
    "goto_3": (-1, 0),    # З
    "goto_4": (1, 0),     # В
    "goto_5": (-1, 1),    # ЮЗ
    "goto_6": (0, 1),     # Ю
    "goto_7": (1, 1),     # ЮВ
}


def goto_name(dx: int, dy: int) -> str | None:
    """Имя шага по смещению; `None`, если такого направления нет."""
    step = (max(-1, min(1, int(dx))), max(-1, min(1, int(dy))))
    for name, d in GOTO_DIRECTIONS.items():
        if d == step:
            return name
    return None


def step_toward(pos: tuple[int, int], target: tuple[int, int],
                offered: Iterable[str] | None = None,
                blocked=None) -> str | None:
    """Шаг из `pos` в сторону `target`: направление, уменьшающее расстояние.

    Берётся знак по каждой оси (шаг «по диагонали», если нужно двигаться по двум осям).
    Если такое направление не предложено миром, ищется любой предложенный шаг, который
    сокращает ШАГОВОЕ расстояние до цели, — иначе `None` (стоять лучше, чем уходить).
    """
    px, py = int(pos[0]), int(pos[1])
    tx, ty = int(target[0]), int(target[1])

    def _enterable(x: int, y: int) -> bool:
        """Законна ли клетка-назначение. §13.350: СПИСОК ПРЕДЛОЖЕНИЙ МИРА — НЕ признак
        законности (измерено: он содержал `produce_Offshore Platform`, которого город строить
        не может). Шаг в воду предлагается, а мира не двигает: поселенец 66-72 раза подряд
        получал `goto_4`/`goto_3` и не сдвигался ни на клетку (измерено §13.348)."""
        return True if blocked is None else not bool(blocked(x, y))

    want = goto_name(tx - px, ty - py)
    offered_set = None if offered is None else {str(x) for x in offered}
    if want is not None and (offered_set is None or want in offered_set):
        dx, dy = GOTO_DIRECTIONS[want]
        if _enterable(px + dx, py + dy):
            return want
    here = max(abs(tx - px), abs(ty - py))
    best = None
    for name, (dx, dy) in GOTO_DIRECTIONS.items():
        if offered_set is not None and name not in offered_set:
            continue
        if not _enterable(px + dx, py + dy):
            continue
        dist = max(abs(tx - (px + dx)), abs(ty - (py + dy)))
        if dist < here and (best is None or dist < best[0]):
            best = (dist, name)
    return None if best is None else best[1]


def _wrap(x: int, y: int, shape) -> tuple[int, int] | None:
    """Клетка после шага: X — цилиндр, за полюсом клетки нет (`map_pos_to_tile`, §13.347)."""
    if shape is None:
        return (int(x), int(y))
    w, h = int(shape[0]), int(shape[1])
    if w > 0:
        x = int(x) % w
    if h > 0 and not 0 <= int(y) < h:
        return None
    return (int(x), int(y))


def path_first_step(pos: tuple[int, int], target: tuple[int, int], passable,
                    *, shape=None, max_nodes: int = 3000) -> tuple[int, int] | None:
    """ПЕРВЫЙ ШАГ КРАТЧАЙШЕГО ПУТИ — перенос его `dai_unit_goto` (`daitools.c:242-291`).

    У него путь ищет маршрутизатор (`pf_map` — обход клеток по цене хода) и юнит идёт по НЕМУ;
    у нас был один ЖАДНЫЙ шаг (`step_toward`), который упирался в воду или в местный минимум и
    стоял: измерено (§13.348) `goto_4`/`goto_3` 66-72 раза подряд без движения. У поселенца один
    ход за ход, поэтому поиск в ширину по восьми соседям даёт ровно цену пути в ходах, как у него.

    `passable(x, y)` — законность клетки (у него это `pf_map` по правилам движения);
    возвращается клетка ПЕРВОГО шага (куда встать), или None, если пути нет.
    """
    start = (int(pos[0]), int(pos[1]))
    goal = (int(target[0]), int(target[1]))
    if start == goal:
        return None
    from collections import deque

    prev: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    queue: deque[tuple[int, int]] = deque([start])
    seen = 0
    while queue and seen < max_nodes:
        cur = queue.popleft()
        seen += 1
        if cur == goal:
            break
        for dx, dy in GOTO_DIRECTIONS.values():
            nxt = _wrap(cur[0] + dx, cur[1] + dy, shape)
            if nxt is None or nxt in prev:
                continue
            if nxt != goal and not bool(passable(nxt[0], nxt[1])):
                continue
            prev[nxt] = cur
            queue.append(nxt)
    if goal not in prev:
        return None
    node = goal
    while prev.get(node) is not None and prev[node] != start:
        node = prev[node]
    return node if prev.get(node) == start else None


def goto_name_to(pos: tuple[int, int], dest: tuple[int, int]) -> str | None:
    """Имя шага `goto_*`, который встаёт РОВНО на `dest` (для хода по найденному пути)."""
    return goto_name(int(dest[0]) - int(pos[0]), int(dest[1]) - int(pos[1]))


def citymindist_blocks(x: int, y: int,
                       cities: Iterable[tuple[int, int]],
                       mindist: int) -> bool:
    """ЕГО ``citymindist_prevents_city_on_tile`` (``common/city.c:1445``).

    Основание запрещено, если ЛЮБОЙ город попадает в квадрат со стороной ``2*(mindist-1)+1``
    вокруг клетки — то есть ``square_iterate(ptile, citymindist - 1)``. Мир отказывает в
    основании именно по этому условию, а наша оценка площадки его не знала: поселенцы
    сгруживались в углу, каждый считал свою клетку лучшей, и города не появлялись.
    """
    r = int(mindist) - 1
    if r < 0:
        return False
    for cx, cy in cities:
        if abs(int(cx) - int(x)) <= r and abs(int(cy) - int(y)) <= r:
            return True
    return False


def rank_sites(obs: dict, *, size: int = 1, exclude: Iterable[tuple[int, int]] = (),
               reference: tuple[int, int] | None = None, move_rate: float = 1.0,
               settler_shield_cost: float = 0.0, limit: int = 200,
               revealed: Iterable[tuple[int, int]] | None = None,
               top: int = 20, cities: Iterable[tuple[int, int]] = (),
               mindist: int = 0, reserved=None) -> list[tuple[int, int, float, float]]:
    """Площадки по ЕГО числам, лучшие первыми: `[(x, y, ai_want, want), …]`.

    Список нужен, а не одна лучшая: у него поселенец идёт по достижимой площадке, и если
    шаг к лучшей невозможен (клетка недостижима для юнита), берётся следующая. Это
    измеренная поправка: без неё поселенец 11 раз подряд выбирал шаг `goto_7` к воде и
    НЕ СДВИГАЛСЯ, то есть вообще не основывал город.

    Перебираются ВИДИМЫЕ клетки; площадки с его флагами голода (`food_starvation` /
    `shield_starvation` из `cityresult_fill`) и занятые городами отбрасываются — ровно как
    у него до подсчёта стоимости (`daisettler.c:800-806`).

    Если задана точка отсчёта (`reference`), применяется ЕГО формула годности назначения:
    ``want = amortize(total, PERFECTION * ходов) − стоимость поселенца`` — та же, что в
    цене поселенца (13.301), через уже перенесённую `settler_want`.
    """
    from env.site_eval import evaluate_site

    map_obs = (obs or {}).get("map") or {}
    if revealed is None:
        from brain.forecast.live import revealed_tiles
        revealed = revealed_tiles(map_obs)
    skip = {(int(x), int(y)) for x, y in exclude}
    # ── §13.353: кольцо запрета вокруг КАЖДОГО известного города (его `citymindist`).
    # Клетки в этом кольце мир площадками не считает, и город там основать нельзя.
    _cities = [(int(cx), int(cy)) for cx, cy in cities]
    _r = int(mindist or 0) - 1
    if _cities and _r >= 0:
        for _cx, _cy in _cities:
            for _dx in range(-_r, _r + 1):
                for _dy in range(-_r, _r + 1):
                    skip.add((_cx + _dx, _cy + _dy))
    found: list[tuple[int, int, float, float]] = []
    # ── §13.355: ЕГО порядок перебора — по возрастанию цены пути (у него это обход
    # маршрутизатора `pf_map_move_costs_iterate`). Без порядка невозможен ни его ранний
    # выход по `RESULT_IS_ENOUGH`, ни честное «хватит искать».
    _iter: list[tuple[float, int, int]] = []
    for _tile in list(revealed)[:limit]:
        _x, _y = int(_tile[0]), int(_tile[1])
        _d = (max(abs(_x - int(reference[0])), abs(_y - int(reference[1])))
              if reference is not None else 0)
        _iter.append((float(_d), _x, _y))
    _iter.sort(key=lambda r: r[0])
    _best_want: float | None = None
    _best_dist: float | None = None
    _seen = 0
    _taken_n = 0
    for _dist, x, y in _iter:
        _seen += 1
        if (x, y) in skip:
            continue
        # ── ЕГО `city_desirability` (`daisettler.c:715-719`): площадка отбрасывается, если
        # ЛЮБАЯ клетка в пределах `citymindist-1` от неё уже занята (`citymap_is_reserved`).
        if reserved is not None:
            _r = max(0, int(mindist or 0) - 1)
            _taken = False
            for _dx in range(-_r, _r + 1):
                for _dy in range(-_r, _r + 1):
                    try:
                        if reserved.is_reserved(x + _dx, y + _dy):
                            _taken = True
                            break
                    except AttributeError:
                        _taken = False
                        break
                if _taken:
                    break
            if _taken:
                _taken_n += 1
                if os.environ.get("DOF_FOUND_DEBUG") == "1":
                    print(f"  [резерв-отказ] площадка {(x, y)}: занято в пределах "
                          f"citymindist-1 (его city_desirability)", flush=True)
                continue
        try:
            site = evaluate_site(map_obs, x, y, size=size)
        except Exception:  # noqa: BLE001
            continue
        if getattr(site, "starved_food", False) or getattr(site, "starved_shield", False):
            continue
        total = float(getattr(site, "ai_want", 0.0) or 0.0)
        if total <= 0.0:
            continue
        want = total
        if reference is not None:
            base = (int(reference[0]), int(reference[1]))
            dist = max(abs(x - base[0]), abs(y - base[1]))
            turns = int(math.ceil(float(dist) / float(move_rate or 1.0))) if dist else 0
            from brain.ai_default.values import settler_want
            want = settler_want(total, travel_turns=turns,
                                settler_shield_cost=float(settler_shield_cost or 0.0))
        found.append((x, y, total, want))
        # ── ЕГО `settler_map_iterate` (`daisettler.c:839-849`): лучшая площадка и её «ходы»
        # помнятся, а выход наступает, когда лучшая уже «достаточно хороша»
        # (`RESULT_IS_ENOUGH`), находится дальше одного хода пути и БЛИЖЕ текущей.
        if _best_want is None or want > _best_want:
            _best_want, _best_dist = want, _dist
        if (_best_want is not None and _best_want > float(RESULT_IS_ENOUGH)
                and _dist > float(move_rate or 1.0)
                and _best_dist is not None and _best_dist < _dist):
            break
    if os.environ.get("DOF_FOUND_DEBUG") == "1":
        _mem = 0
        try:
            from env.world_memory import CALLS as _mc
            _mem = int(_mc.get("tiles") or 0)
        except Exception:  # noqa: BLE001
            pass
        print(f"  [поиск] рассмотрено {_seen}, отброшено местом {_taken_n}, годных {len(found)}, "
              f"память {_mem}", flush=True)
    found.sort(key=lambda r: -r[3])
    return found[:max(1, int(top))]


def city_positions(obs: dict) -> set[tuple[int, int]]:
    """Клетки, занятые ЛЮБЫМ видимым городом: у него такие площадками не считаются."""
    out: set[tuple[int, int]] = set()
    cities = (obs or {}).get("city")
    if not isinstance(cities, dict):
        return out
    for rec in cities.values():
        if not isinstance(rec, dict):
            continue
        if rec.get("x") is None or rec.get("y") is None:
            continue
        try:
            out.add((int(rec["x"]), int(rec["y"])))
        except (TypeError, ValueError):
            continue
    return out
