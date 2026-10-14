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
from typing import Any, Iterable

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
                offered: Iterable[str] | None = None) -> str | None:
    """Шаг из `pos` в сторону `target`: направление, уменьшающее расстояние.

    Берётся знак по каждой оси (шаг «по диагонали», если нужно двигаться по двум осям).
    Если такое направление не предложено миром, ищется любой предложенный шаг, который
    сокращает ШАГОВОЕ расстояние до цели, — иначе `None` (стоять лучше, чем уходить).
    """
    px, py = int(pos[0]), int(pos[1])
    tx, ty = int(target[0]), int(target[1])
    want = goto_name(tx - px, ty - py)
    offered_set = None if offered is None else {str(x) for x in offered}
    if want is not None and (offered_set is None or want in offered_set):
        return want
    here = max(abs(tx - px), abs(ty - py))
    best = None
    for name, (dx, dy) in GOTO_DIRECTIONS.items():
        if offered_set is not None and name not in offered_set:
            continue
        dist = max(abs(tx - (px + dx)), abs(ty - (py + dy)))
        if dist < here and (best is None or dist < best[0]):
            best = (dist, name)
    return None if best is None else best[1]


def rank_sites(obs: dict, *, size: int = 1, exclude: Iterable[tuple[int, int]] = (),
               reference: tuple[int, int] | None = None, move_rate: float = 1.0,
               settler_shield_cost: float = 0.0, limit: int = 200,
               revealed: Iterable[tuple[int, int]] | None = None,
               top: int = 20) -> list[tuple[int, int, float, float]]:
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
    found: list[tuple[int, int, float, float]] = []
    for tile in list(revealed)[:limit]:
        x, y = int(tile[0]), int(tile[1])
        if (x, y) in skip:
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
    found.sort(key=lambda r: -r[3])
    return found[:max(1, int(top))]


def best_site(obs: dict, **kwargs):
    """Лучшая площадка — первый из `rank_sites` (совместимость и читаемость)."""
    got = rank_sites(obs, **kwargs)
    return got[0] if got else None


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
