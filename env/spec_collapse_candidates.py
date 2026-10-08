"""Кандидаты «возможного источника коллапса» по наблюдению (§13.64).

Правило владельца модели (2026-10-07):
  * напавшего и защитника различаем по клетке — юнит, стоящий на клетке СВОЕГО игрока,
    считается защитником;
  * если признак клетки недоступен, КАНДИДАТАМИ объявляются оба воюющих юнита;
  * кандидатом объявляется и любой посторонний юнит, зашедший на нашу территорию или
    обнаруженный в пределах открытых (исследованных) клеток.

Модуль чистый: он ничего не помечает в ядре. Метка `is_collapse_source` — ВХОД ядра
`v0.11` (`brain/spec/hypothesis.py`: гипотеза не вправе её менять), поэтому
подтверждённая метка ставится отдельно (`env/spec_attack.py`), а кандидат живёт здесь —
со своей причиной, отдельно от подтверждённой пометки.

Кандидат ≠ подтверждённая метка: кандидат — подозрение с названной причиной, которое
держится, пока первичное нападение не наблюдено (срок держания — `COLLAPSE_HORIZON`).

Два готовых читателя мира НЕ переизобретаются здесь (правило «один читатель на проект»):
чужой канал карты читает `env.spec_threat.foreign_units_from_map` (он же знает пустышку
`255` и порядок индексов `map.unit_owner[y][x]`), и наши сущности из среза — `slice_of`.
Слой `tile_owner` индексируется ТАМ ЖЕ порядком `[y][x]`: на форме 78×52 оба порядка дают
валидные индексы, поэтому «догадка порядка» молча читала бы чужую клетку.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from env import spec_threat as T

#: Слой карты с владельцем клетки.
TILE_OWNER = "tile_owner"

#: Пустышка «юнита/владельца нет» (замер `v2`, тот же смысл, что в `spec_threat`).
EMPTY = 255


def _layer(obs: Mapping[str, Any], name: str) -> Any:
    return ((obs or {}).get("map") or {}).get(name)


def _cell(layer: Any, x: Any, y: Any) -> Optional[int]:
    """Значение клетки в порядке мира `[y][x]`; `None`, если недоступно.

    Порядок один и назван явно: подбирать его «на удачу» нельзя — при форме 78×52
    оба порядка валидны, и подбор молча вернул бы владельца ЧУЖОЙ клетки.
    """
    if layer is None or x is None or y is None:
        return None
    try:
        xi, yi = int(x), int(y)
    except (TypeError, ValueError):
        return None
    try:
        value = layer[yi][xi]
    except (IndexError, KeyError, TypeError):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def tile_owner_at(obs: Mapping[str, Any], x: Any, y: Any) -> Optional[int]:
    """Владелец клетки или `None`, если мир этого не публикует.

    Пустышка слоя читается как «владельца нет» — `None`, а не ноль: «нет данных» и
    «владелец 0» (наш игрок) — разные вещи.
    """
    value = _cell(_layer(obs, TILE_OWNER), x, y)
    if value is None or value == EMPTY:
        return None
    return value


def foreign_units(obs: Mapping[str, Any], my_player_id: Any = 0) -> list[dict[str, Any]]:
    """Видимые чужие юниты: единый канал проекта + наши из секции `unit`, если владелец чужой."""
    out: list[dict[str, Any]] = []
    for owner, x, y in T.foreign_units_from_map(obs, my_player_id):
        out.append({"id": f"foe_{owner}_{x}_{y}", "owner": owner, "x": x, "y": y})
    try:
        me = int(my_player_id)
    except (TypeError, ValueError):
        me = 0
    units = (obs or {}).get("unit")
    if isinstance(units, Mapping):
        have = {(u["x"], u["y"]) for u in out}
        for key, rec in units.items():
            if not isinstance(rec, Mapping):
                continue
            try:
                owner = int(rec.get("owner", me))
                x, y = int(rec["x"]), int(rec["y"])
            except (KeyError, TypeError, ValueError):
                continue
            if owner != me and (x, y) not in have:
                out.append({"id": str(key), "owner": owner, "x": x, "y": y})
    return out


def standing_on_own_tile(obs: Mapping[str, Any], owner: Any, x: Any, y: Any) -> Optional[bool]:
    """Стоит ли юнит на клетке своего игрока: `True` / `False` / `None` (признак недоступен)."""
    try:
        u = int(owner)
    except (TypeError, ValueError):
        return None
    t = tile_owner_at(obs, x, y)
    if t is None:
        return None            # владелец клетки не наблюдён — признак НЕДОСТУПЕН
    return bool(t == u)


def classify_pair(obs: Mapping[str, Any],
                  a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """Разделить двух воюющих юнитов по клеткам.

    Каждый участник — запись с полями `owner`, `x`, `y` (и `id` для отчёта).
    Возврат: `{"attacker", "defender", "candidates", "reason"}`. Признак клетки
    недоступен хотя бы у одного — КАНДИДАТАМИ объявляются оба (решение владельца).
    """
    va = standing_on_own_tile(obs, a.get("owner"), a.get("x"), a.get("y"))
    vb = standing_on_own_tile(obs, b.get("owner"), b.get("x"), b.get("y"))

    if va is None or vb is None:
        return {"attacker": None, "defender": None,
                "candidates": [dict(a, why="признак клетки недоступен"),
                               dict(b, why="признак клетки недоступен")],
                "reason": "владелец клетки не наблюдён — кандидатами объявлены оба воюющих"}

    if va and vb:
        return {"attacker": None, "defender": None,
                "candidates": [dict(a, why="оба стоят на своих клетках"),
                               dict(b, why="оба стоят на своих клетках")],
                "reason": "оба участника на своих клетках — нападающий не различим"}

    if not va and not vb:
        return {"attacker": None, "defender": None,
                "candidates": [dict(a, why="оба на чужих клетках"),
                               dict(b, why="оба на чужих клетках")],
                "reason": "ни один не стоит на своей клетке — нападающий не различим"}

    attacker, defender = (b, a) if va else (a, b)
    return {"attacker": attacker, "defender": defender, "candidates": [],
            "reason": "стоящий на чужой клетке — нападающий, на своей — защитник"}


def extraneous_candidates(obs: Mapping[str, Any], my_player_id: Any,
                          known_tiles: Optional[Iterable[Sequence[Any]]] = None
                          ) -> list[dict[str, Any]]:
    """Посторонние юниты на нашей территории или в пределах открытых клеток.

    «Открытые клетки» — множество, которое помнит сам мир (слой `status`: 1 — видно
    сейчас, 2 — известно); если `known_tiles` не задан, беру его из слоя.
    """
    try:
        me = int(my_player_id)
    except (TypeError, ValueError):
        return []

    known: Optional[set[tuple[int, int]]] = None
    if known_tiles is not None:
        known = {(int(x), int(y)) for x, y in known_tiles}
    else:
        status = _layer(obs, "status")
        if status is not None:
            known = set()
            try:
                ys, xs = len(status), len(status[0])
            except (TypeError, IndexError):
                known = None
            if known is not None:
                for y in range(ys):
                    for x in range(xs):
                        if _cell(status, x, y) in (1, 2):
                            known.add((x, y))

    out: list[dict[str, Any]] = []
    for u in foreign_units(obs, me):
        x, y = u["x"], u["y"]
        on_our_soil = tile_owner_at(obs, x, y) == me
        inside_known = bool(known is not None and (x, y) in known)
        if on_our_soil or inside_known:
            out.append(dict(u, why=("посторонний юнит на нашей территории" if on_our_soil
                                    else "посторонний юнит в пределах открытых клеток")))
    return out


def _city_tiles(obs: Mapping[str, Any]) -> dict[tuple[int, int], int]:
    """Клетки с городом и их владельцы (слой `city_owner`)."""
    grid = _layer(obs, "city_owner")
    out: dict[tuple[int, int], int] = {}
    if grid is None:
        return out
    try:
        ys, xs = len(grid), len(grid[0])
    except (TypeError, IndexError):
        return out
    for y in range(ys):
        for x in range(xs):
            v = _cell(grid, x, y)
            if v is not None and v != EMPTY:
                out[(x, y)] = v
    return out


def loss_events(prev: Mapping[str, Any], obs: Mapping[str, Any],
                my_player_id: Any = 0) -> list[dict[str, Any]]:
    """Чужие потери между двумя наблюдениями: юнит исчез, город исчез или сменил владельца.

    Жертвой считается ЧУЖАЯ сущность: владелец модели (2026-10-07) приравнял нападение на
    третью сторону к нападению на нас. Наши потери считает `env.spec_attack`, здесь они
    не дублируются.
    """
    try:
        me = int(my_player_id)
    except (TypeError, ValueError):
        me = 0
    prev_units = {(u["x"], u["y"]): u for u in foreign_units(prev, me)}
    now_units = {(u["x"], u["y"]): u for u in foreign_units(obs, me)}

    events: list[dict[str, Any]] = []
    for pos, u in prev_units.items():
        if pos not in now_units:
            events.append({"kind": "unit", "owner": u["owner"], "x": u["x"], "y": u["y"],
                           "why": "чужой юнит исчез между срезами"})

    prev_cities, now_cities = _city_tiles(prev), _city_tiles(obs)
    for pos, owner in prev_cities.items():
        if owner == me:
            continue
        new_owner = now_cities.get(pos)
        if new_owner != owner:
            events.append({"kind": "city", "owner": owner, "x": pos[0], "y": pos[1],
                           "new_owner": new_owner,
                           "why": ("чужой город перешёл другому игроку" if new_owner not in (None, me)
                                   else "чужой город исчез между срезами")})
    return events


def classify_loss(obs: Mapping[str, Any], event: Mapping[str, Any],
                  my_player_id: Any = 0) -> dict[str, Any]:
    """Кто мог нанести потерю: видимые чужие рядом с местом события, разделённые по клетке.

    Ни одного видимого чужого рядом — «нападающий не наблюдён», кандидатов нет: догадка
    из тумана кандидатом не становится.
    """
    x, y = int(event["x"]), int(event["y"])
    near = [u for u in foreign_units(obs, my_player_id)
            if abs(int(u["x"]) - x) <= 1 and abs(int(u["y"]) - y) <= 1]
    if not near:
        return {"candidates": [], "attacker": None, "defender": None,
                "reason": "нападающий не наблюдён — рядом с местом потери чужих нет"}
    if len(near) == 1:
        return {"candidates": [dict(near[0], why="единственный чужой рядом с местом потери")],
                "attacker": None, "defender": None,
                "reason": "единственный видимый чужой рядом — кандидат"}
    res = classify_pair(obs, near[0], near[1])
    res["reason"] = "двое видимых чужих рядом с местом потери: " + str(res["reason"])
    return res


def observe_candidates(prev: Optional[Mapping[str, Any]], obs: Mapping[str, Any],
                       my_player_id: Any = 0, turn: Any = None) -> dict[str, Any]:
    """Кандидаты «возможного источника коллапса» по двум срезам (§13.64).

    Возврат: `{"turn", "extraneous", "losses", "candidates", "reason"}`. Каждый кандидат —
    словарь с `why` (названная причина) и `source` (`extraneous` / `loss`). Пусто — С
    НАЗВАННОЙ причиной, а не молчанием: «не наблюдено» и «никого нет» — разные вещи
    (правило проекта: ноль обязан называть, какой он).

    Сравнивать надо СЫРЫЕ наблюдения (урок `spec_attack.observe`: срез вместо наблюдения
    давал «потерь не наблюдено» на синтетике с наблюдаемым нападением).
    """
    extraneous = extraneous_candidates(obs, my_player_id)
    losses: list[dict[str, Any]] = []
    if prev is not None:
        for event in loss_events(prev, obs, my_player_id):
            losses.append({**event, **classify_loss(obs, event, my_player_id)})

    candidates: list[dict[str, Any]] = []
    for u in extraneous:
        candidates.append({**u, "source": "extraneous"})
    for item in losses:
        for c in item.get("candidates", []):
            candidates.append({**c, "source": "loss", "loss_kind": item.get("kind"),
                               "at": [item.get("x"), item.get("y")]})

    if candidates:
        reason = (f"кандидатов {len(candidates)}: посторонних на нашей земле или в открытых "
                  f"клетках {len(extraneous)}, при потерях {len(losses)}")
    elif prev is None:
        reason = "предыдущего среза нет — сравнить нечем, кандидатов нет"
    else:
        reason = ("чужих рядом с местами потерь и посторонних на нашей земле не видно — "
                  "кандидатов нет")
    return {"turn": turn, "extraneous": extraneous, "losses": losses,
            "candidates": candidates, "reason": reason}
