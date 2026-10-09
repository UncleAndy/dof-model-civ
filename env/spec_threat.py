"""Угроза и источник коллапса — факты из ветки `v2` (§10.70–10.75 её журнала).

Под рамку `v0.11` переносятся **факты о мире**, а не выводы прежнего измерителя.

1. **Геометрия шага** (`DIR8_OFFSETS`). `goto_N` и `attack_N` — ОДИН шаг в направлении
   dir8: `ActGoto`/`ActAttack` идут через `mapstep(ptile, dir8)`, а тот —
   `map_pos_to_tile(DIR_DX[dir8] + x, DIR_DY[dir8] + y)`. Таблица подтверждена ДВУМЯ
   независимыми источниками: живым замером `v2` (8 партий, по шагу на партию) и
   вендорскими константами на диске
   (`civrealm/src/civrealm/freeciv/map/map_const.py:60-61`).
2. **Канал видимости чужих** (`foreign_units_from_map`). В наблюдении есть карта
   `map.unit_owner` (клетка → владелец юнита, 255 = нет юнита): чужой **виден** там,
   даже когда его паспорта нет в секции `unit` (замер `v2`: в 113 решениях секция
   `unit` не отдала ни одного чужого, а мир в тех же партиях фиксировал `city_lost: 2`
   и `unit/attack: 1` — «никого» и «сенсора нет» были неотличимы, пока не появился
   счётчик второго канала).
3. **Чужой без паспорта** (`mean_attack`). Сила чужого, паспорт которого не
   опубликован, моделируется **средним по известным** (`type_attack_strength`
   наблюдённых юнитов), а не нулём: нуль был бы утверждением «безобиден» ровно
   потому, что мы о нём ничего не знаем.
4. **Нападение — только по наблюдённому** (`observed_attack`). Решения владельца
   модели: мирные чужие ПЛЮСУЮТСЯ; нападение считается состоявшимся, только если его
   видно на раскрытых клетках («догадка из тумана нападением не считается»); признак
   источника держится **весь срок прогноза** (`COLLAPSE_HORIZON` = 20 ходов), а не
   один ход. Признак ставится сравнением двух ПОЛНЫХ срезов: наша сущность исчезла
   (и это не объясняется нашим собственным измеренным действием — `build_city` /
   `join_city` мир публикует как потребляющие юнита) **или** её здоровье упало,
   **и** на смежной клетке текущего среза виден чужой. Нет видимого соседа — виновный
   не назначается: пишется «нападающий не наблюдён».
5. **Знак источника** (`counted`). Сущность, помеченная источником коллапса,
   **исключается** из счёта с причиной «его возможности не наши»; мирные чужие
   продолжают плюсоваться.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from env.config import SPEC_COLLAPSE_HORIZON_TURNS

#: Смещения одного шага dir8 (порядок: NW, N, NE, W, E, SW, S, SE).
#: Источник: вендорские `DIR_DX` / `DIR_DY` (`map_const.py:60-61`), совпавшие с живым
#: замером `v2` до знака. `goto_N`/`attack_N` — ОДИН шаг, а не «N есть dir8 и цель
#: вычислима»: прежняя запись была догадкой, пока замер её не подтвердил.
DIR8_OFFSETS: tuple[tuple[int, int], ...] = (
    (-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1),
)


def step(x: int, y: int, dir_index: int) -> tuple[int, int]:
    """Клетка после ОДНОГО шага в направлении `dir_index`."""
    dx, dy = DIR8_OFFSETS[int(dir_index) % len(DIR8_OFFSETS)]
    return int(x) + dx, int(y) + dy


def adjacent(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Смежность по Чебышёву: «вплотную» = максимум разностей ≤ 1."""
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1]))) == 1


def _our_units(obs: Mapping[str, Any], my_player_id: Any) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for key, rec in ((obs or {}).get("unit") or {}).items():
        if not isinstance(rec, Mapping):
            continue
        if int(rec.get("owner", my_player_id) or my_player_id) == int(my_player_id):
            out[str(key)] = rec
    return out


def _our_cities(obs: Mapping[str, Any], my_player_id: Any) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for key, rec in ((obs or {}).get("city") or {}).items():
        if not isinstance(rec, Mapping):
            continue
        if int(rec.get("owner", my_player_id) or my_player_id) == int(my_player_id):
            out[str(key)] = rec
    return out


def foreign_units_from_map(obs: Mapping[str, Any], my_player_id: Any = 0
                           ) -> list[tuple[int, int, int]]:
    """Чужие юниты из карты `map.unit_owner`: список `(владелец, x, y)`.

    Карта — **второй канал**: паспорта чужого в секции `unit` может не быть, а на
    карте он виден. Значение `255` означает «юнита нет» (замер `v2`), свои клетки
    не возвращаются. Порядок слоя — `map.unit_owner[x][y]` (§13.99, измерено на своих
    юнитах: чтение `[x][y]` даёт наш id четыре раза из четырёх, `[y][x]` — ни разу),
    поэтому и тройка возвращается в том же смысле: `(владелец, x, y)`.
    """
    grid = ((obs or {}).get("map") or {}).get("unit_owner")
    if not isinstance(grid, Sequence):
        return []
    found: list[tuple[int, int, int]] = []
    for x, column in enumerate(grid):
        if not isinstance(column, Sequence):
            continue
        for y, value in enumerate(column):
            try:
                owner = int(value)
            except (TypeError, ValueError):
                continue
            if owner == 255 or owner == int(my_player_id):
                continue
            found.append((owner, x, y))
    return found


def mean_attack(obs: Mapping[str, Any], my_player_id: Any = 0) -> tuple[Optional[float], int]:
    """Средняя атака по ИЗВЕСТНЫМ типам и их число.

    «Известные типы» — то, что мир ПУБЛИКУЕТ о типах: спецификации `sup_units` /
    `sup_improvements` в записях технологий (`attack_strength`), а не только паспорта
    наших юнитов. Замер 2026-10-06 на живом срезе: каталог спек даёт **48 записей,
    средняя 7.02** (боевых типов с атакой > 0 — 38), а усреднение по ОДНИМ нашим
    юнитам — **0.0 по 4 типам** (все мирные). То есть чужой выглядел бы безобидным
    ровно потому, что мы знаем только своих, — тот самый отказ, ради которого правило
    заведено. Объединение каталога с наблюдёнными юнитами даёт среднюю **6.48 по 52**.
    Паспорт чужого с карты (`map.unit_owner`) не публикуется, поэтому его сила берётся
    этим средним, а не нулём. Ничего не известно — `None` и `n = 0` («нечего
    усреднять»), а не ноль; число `n` возвращается, чтобы у вызывающего была видна
    ОСНОВА среднего.
    """
    seen: list[float] = []
    for tech in ((obs or {}).get("tech") or {}).values():
        if not isinstance(tech, Mapping):
            continue
        for key in ("sup_units", "sup_improvements"):
            for spec in (tech.get(key) or []):
                if not isinstance(spec, Mapping):
                    continue
                raw = spec.get("attack_strength", spec.get("attack"))
                if raw is None:
                    continue
                try:
                    seen.append(float(raw))
                except (TypeError, ValueError):
                    continue
    for layer in ("unit", "player"):
        recs = (obs or {}).get(layer) or {}
        if not isinstance(recs, Mapping):
            continue
        for rec in recs.values():
            if not isinstance(rec, Mapping):
                continue
            raw = rec.get("type_attack_strength")
            if raw is None:
                continue
            try:
                seen.append(float(raw))
            except (TypeError, ValueError):
                continue
    if not seen:
        return None, 0
    return sum(seen) / float(len(seen)), len(seen)


#: Срок держания признака «источник коллапса» — объявлен ДО данных (§10.73).
COLLAPSE_HORIZON: int = SPEC_COLLAPSE_HORIZON_TURNS


def observed_attack(prev: Mapping[str, Any], cur: Mapping[str, Any],
                    my_player_id: Any = 0,
                    consumed_by_us: Iterable[str] = (),
                    horizon: int = COLLAPSE_HORIZON) -> dict[str, Any]:
    """Наблюдённое нападение между двумя ПОЛНЫМИ срезами.

    Возвращает объявление, а не догадку: `attacked`, пострадавших (`victims`),
    найденных нападавших (`attackers`, пустой список = «нападающий не наблюдён»)
    и срок держания признака (`hold_turns`). Сравнение среза ПРОШЛОЙ партии с первым
    срезом новой нападением не считается: нет предыдущего среза — нет события.
    """
    consumed = {str(x) for x in consumed_by_us}
    if not prev:
        return {"attacked": False, "victims": [], "attackers": [],
                "hold_turns": int(horizon), "reason": "предыдущего среза нет"}

    victims: list[dict[str, Any]] = []
    prev_units = _our_units(prev, my_player_id)
    cur_units = _our_units(cur, my_player_id)
    for uid, before in prev_units.items():
        if uid in consumed:
            continue
        after = cur_units.get(uid)
        if after is None:
            victims.append({"id": f"unit_{uid}", "how": "исчезла",
                            "x": before.get("x"), "y": before.get("y")})
            continue
        try:
            hb, ha = float(before.get("health")), float(after.get("health"))
        except (TypeError, ValueError):
            continue
        if ha < hb:
            victims.append({"id": f"unit_{uid}", "how": f"health {hb:g} → {ha:g}",
                            "x": after.get("x"), "y": after.get("y")})

    cur_cities = _our_cities(cur, my_player_id)
    for cid, before in _our_cities(prev, my_player_id).items():
        if cid in consumed or cid in cur_cities:
            continue
        victims.append({"id": f"city_{cid}", "how": "исчез",
                        "x": before.get("x"), "y": before.get("y")})

    if not victims:
        return {"attacked": False, "victims": [], "attackers": [],
                "hold_turns": int(horizon),
                "reason": "потерь и ранений наших сущностей не наблюдено"}

    foreigners = foreign_units_from_map(cur, my_player_id)
    attackers: list[tuple[int, int, int]] = []
    for victim in victims:
        if victim.get("x") is None or victim.get("y") is None:
            continue
        for foe in foreigners:
            if adjacent((victim["x"], victim["y"]), (foe[1], foe[2])) and foe not in attackers:
                attackers.append(foe)
    reason = ("нападающий наблюдён на смежной клетке" if attackers
              else "нападающий не наблюдён: виновный не назначается")
    return {"attacked": True, "victims": victims, "attackers": attackers,
            "hold_turns": int(horizon), "reason": reason}


def counted(entities: Iterable[str], collapse_sources: Iterable[str]
            ) -> tuple[list[str], list[tuple[str, str]]]:
    """Счёт по §10.33: источник коллапса исключается, мирные чужие плюсуются.

    Возвращает то, что считается, и исключённых с ПРИЧИНОЙ — «его возможности не
    наши»: знак угрозы был неверным, пока атакующий прибавлял системе свои опции.
    """
    sources = {str(x) for x in collapse_sources}
    kept: list[str] = []
    dropped: list[tuple[str, str]] = []
    for entity in entities:
        name = str(entity)
        if name in sources:
            dropped.append((name, "его возможности не наши"))
        else:
            kept.append(name)
    return kept, dropped
