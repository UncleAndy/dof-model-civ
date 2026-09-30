"""Наблюдённые эффекты переходов — пища проекции.

ЧТО И ПОЧЕМУ. Проекция обязана быть измеренной, а не выдуманной. Источник измерения уже есть в
стенде: **реальное действие ход не двигает** (измерено в v1, закреплено в харнессе), поэтому
разница состояний «до» и «после» реального действия — это эффект **нашего** действия, а не хода
мира. Разница вокруг шага `None` (закрытие хода) — это, наоборот, ход мира; её пишем отдельно.

Снимок берём только по нашей стороне (свои юниты, свои города, своё состояние игрока, свои
технологии) плюс число раскрытых клеток: чужие действия в наш снимок не попадают, и эффект
остаётся чистым.
"""
from __future__ import annotations

from typing import Any

UNKNOWN_TERRAIN = 255


def _seq(v) -> list:
    """Мир отдаёт массивы как numpy/BitVector: `v or []` на них падает."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    try:
        return list(v)
    except TypeError:
        return []


def _count_true(x) -> int:
    """Сколько истинных бит в структуре (BitVector, списки, вложенные списки)."""
    if x is None:
        return 0
    if isinstance(x, bool):
        return 1 if x else 0
    if isinstance(x, int):
        return 1 if x else 0
    try:
        items = list(x)
    except TypeError:
        return 0
    return sum(_count_true(i) for i in items)


def snapshot(obs: dict, own_id: int = 0) -> dict[str, Any]:
    """Компактный снимок нашей стороны — из чего считается эффект перехода."""
    units: dict[str, list] = {}
    for uid, u in (obs.get("unit") or {}).items():
        if not isinstance(u, dict) or u.get("owner") != own_id:
            continue
        units[str(uid)] = [u.get("type_rule_name"), u.get("x"), u.get("y"), u.get("moves_left")]

    cities: dict[str, list] = {}
    for cid, c in (obs.get("city") or {}).items():
        if not isinstance(c, dict) or c.get("owner") != own_id:
            continue
        # 4-й элемент — число разрешённых позиций постройки: это и есть DoF города, поэтому
        # рост меню (например, от новой технологии) виден как измеренный факт.
        buildable = sum(1 for v in _seq(c.get("can_build_unit")) if v)
        cities[str(cid)] = [c.get("size"), c.get("surplus_food"), c.get("shield_stock"),
                            c.get("turns_to_prod_complete"), buildable]

    players = obs.get("player") or {}
    p = players.get(str(own_id)) or players.get(own_id) or {}
    tech: dict[str, int] = {}
    for tid, t in (obs.get("tech") or {}).items():
        if isinstance(t, dict) and t.get("inv_state"):
            tech[str(tid)] = int(t.get("inv_state"))

    revealed = 0
    for col in _seq((obs.get("map") or {}).get("terrain")):
        for v in _seq(col):
            if int(v) != UNKNOWN_TERRAIN:
                revealed += 1

    # Изменения местности (дороги, орошение, шахты). В записи юнита длящийся процесс НЕ виден
    # (проверено: 23 поля, ни одного про активность), поэтому работу ловим по клеткам.
    extras_true = _count_true((obs.get("map") or {}).get("extras"))

    return {"units": units, "cities": cities,
            "player": {k: p.get(k) for k in ("gold", "science", "bulbs_researched",
                                             "researching", "government")},
            "tech": tech, "revealed": revealed, "extras_true": extras_true}


def diff(before: dict, after: dict) -> dict[str, int]:
    """Что изменилось. Ключи — измеренные события, не интерпретации."""
    ch: dict[str, int] = {}

    def bump(k: str, n: int = 1) -> None:
        ch[k] = ch.get(k, 0) + n

    # юниты
    for uid, b in before["units"].items():
        a = after["units"].get(uid)
        if a is None:
            bump("unit_lost")
            continue
        if (b[1], b[2]) != (a[1], a[2]):
            bump("unit_moved")
        if b[0] != a[0]:
            bump("unit_type_changed")
        if isinstance(b[3], int) and isinstance(a[3], int) and a[3] != b[3]:
            bump("unit_moves_changed")
    for uid in after["units"]:
        if uid not in before["units"]:
            bump("unit_new")

    # города
    for cid, b in before["cities"].items():
        a = after["cities"].get(cid)
        if a is None:
            bump("city_lost")
            continue
        if isinstance(b[0], int) and isinstance(a[0], int) and a[0] > b[0]:
            bump("city_grew")
        if isinstance(b[0], int) and isinstance(a[0], int) and a[0] < b[0]:
            bump("city_shrank")
        if isinstance(b[2], int) and isinstance(a[2], int) and a[2] != b[2]:
            bump("city_shields_changed")
        if b[3] != a[3]:
            bump("city_prod_eta_changed")
        if isinstance(b[4], int) and isinstance(a[4], int) and a[4] != b[4]:
            bump("city_buildable_delta", int(a[4] - b[4]))
    for cid in after["cities"]:
        if cid not in before["cities"]:
            bump("city_new")

    # состояние игрока
    for k in ("gold", "science", "bulbs_researched"):
        b, a = before["player"].get(k), after["player"].get(k)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)) and a != b:
            bump(f"player_{k}_delta", int(a - b))
    if before["player"].get("researching") != after["player"].get("researching"):
        bump("researching_changed")
    if before["player"].get("government") != after["player"].get("government"):
        bump("government_changed")

    # технологии: считаем переходы состояния, не толкуя шкалу
    for tid, b in before["tech"].items():
        a = after["tech"].get(tid)
        if a is not None and a != b:
            bump(f"tech_state_{b}to{a}")
    for tid in after["tech"]:
        if tid not in before["tech"]:
            bump(f"tech_entered_{after['tech'][tid]}")

    if after["revealed"] != before["revealed"]:
        bump("revealed_delta", int(after["revealed"] - before["revealed"]))
    if after.get("extras_true", 0) != before.get("extras_true", 0):
        bump("extras_delta", int(after.get("extras_true", 0) - before.get("extras_true", 0)))

    return ch


def new_and_lost(changes: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
    """Сущности, появившиеся и исчезнувшие, — из измеренного изменения снимка."""
    new = {k[:-4]: v for k, v in changes.items() if k.endswith("_new") and v > 0}
    lost = {k[:-5]: v for k, v in changes.items() if k.endswith("_lost") and v > 0}
    return new, lost