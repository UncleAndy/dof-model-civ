"""Правило F «еда необратима» — одно правило на проект (замер: `DOF_CALIBRATION.md` §10.30).

**Что запрещено и на каком замере это стоит** (живые данные, 6 игроков, серии 12 × 14
и 3 × 10, ветвь без прогноза):

    surplus_food = prod_food − food_cost × размер      — совпало 59 из 59 наблюдений
    food_cost = 2                                       — из правил мира (`obs['rules']`)
    surplus_food = 0                                    — город жив (79 наблюдений)
    surplus_food < 0                                    — «Famine …» и уничтожение города
    `city_unwork_<idx>_<dx>_<dy>` убирает еду ЦЕЛЕВОЙ клетки  — подтверждено точно
                                                        (3 − 2 = 1 еды, surplus +1 → −1)
    еда клеток вокруг своих городов: 0…3 (4155 клеток), максимум 3
    `join_city` — плюс один житель, то есть плюс `food_cost` расхода

**Почему правило вообще нужно.** Город размера 1 при `surplus_food < 0` уничтожается
целиком, а поселенец к этому моменту уже потрачен на основание: сторона теряет
единственный город И остаётся без поселенцев, то есть выбывает из игры. Это
НЕОБРАТИМОЕ следствие обратимого на вид выбора из меню — ровно то, что аксиома 3/4
DOF-Core запрещает оплачивать экспериментом.

**Что правило НЕ делает.** Оно не оценивает выгоду и не выбирает за политику: оно
отсекает три семейства в момент ФОРМИРОВАНИЯ кандидатов, чтобы поиск ранжировал уже
безопасный список (вето задним числом оставило бы сторону без хода, хотя безопасная
альтернатива была). Ни основание города, ни производство, ни покупка, ни движение,
ни работы, ни наука, ни дипломатия не затрагиваются.
"""

from __future__ import annotations

from typing import Any

#: Семейства, к которым применяется правило.
UNWORK = "city_unwork_"
SPECIALIST = "city_change_specialist"
JOIN = "join_city"

#: `food_cost` по умолчанию — из правил мира; берётся из `obs['rules']`, если есть.
DEFAULT_FOOD_COST = 2.0
#: §13.432: разрешения на обмен «снять плохую → занять лучшую», выданные управляющим на ход.
#: Ключ — id города, значение — (смещение, избыток еды ПОСЛЕ обмена, размер, food_cost).
_SWAP_ALLOWANCE: dict = {}
#: Наибольшая измеренная еда клетки вокруг своих городов (4155 клеток): граница
#: консервативной ветви для `city_change_specialist`, цена которого из имени не видна.
MAX_TILE_FOOD = 3.0

#: Счётчики отказов — чтобы результат правила был виден в отчёте, а не тонул в тишине.
_DENIALS: dict[str, int] = {}
_EXAMPLES: list[str] = []
#: Журнал РЕШЕНИЙ правила: с какими числами оно смотрело на каждое действие и что
#: решило. Нужен потому, что состояние внутри хода меняется от действия к действию, и
#: сверка «по состоянию на начало хода» даёт ложные протечки (измерено: 167 ложных).
_DECISIONS: list[dict] = []
_DECISION_CAP = 4000


def reset_log() -> None:
    """Обнулить счётчики и журнал решений (в начале матча)."""
    _DENIALS.clear()
    _EXAMPLES.clear()
    _DECISIONS.clear()


def decision_log() -> list[dict]:
    """Журнал решений: `{turn, name, surplus, loss, deny, bound}`."""
    return list(_DECISIONS)


def denial_report() -> dict[str, Any]:
    """Что и сколько раз правило запретило; плюс первые примеры с числами."""
    return {"counts": dict(_DENIALS), "examples": list(_EXAMPLES),
            "total": sum(_DENIALS.values())}


def _note(record: dict) -> None:
    if len(_DECISIONS) < _DECISION_CAP:
        _DECISIONS.append(record)


def _tally(family: str, example: str) -> None:
    _DENIALS[family] = _DENIALS.get(family, 0) + 1
    if len(_EXAMPLES) < 12:
        _EXAMPLES.append(example)


def _plain(value):
    """numpy-массив → список. Живое наблюдение отдаёт карту массивом, и булевы
    проверки на значениях мира падают (`ValueError: truth value … ambiguous`)."""
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:  # noqa: BLE001
            return value
    return value


def tile_food(obs: dict, x, y):
    """Еда клетки по (x, y) или `None`, если её не видно.

    Ориентация измерена на живых данных: `map.output[x][y]`, вектор
    `[еда, щиты, торговля, 0, 0, 0]`. Карта — **цилиндр**: X замыкается
    (измерено: `wrap_id = 1`, X True, Y False), поэтому отрицательный X читается по
    модулю, а выход Y за границу — не «нулевая клетка», а `None` (незнание).
    Без этого `out[-2]` молча вернул бы ЧУЖУЮ клетку.
    """
    mp = (obs or {}).get("map")
    if not isinstance(mp, dict) or x is None or y is None:
        return None
    out = _plain(mp.get("output"))
    if not isinstance(out, list) or not out:
        return None
    rows = len(out)
    cols = len(out[0]) if hasattr(out[0], "__len__") else 0
    if not cols:
        return None
    try:
        ix, iy = int(x), int(y)
    except (TypeError, ValueError):
        return None
    if iy < 0 or iy >= cols:
        return None
    ix %= rows                      # цилиндр по X
    try:
        vec = out[ix][iy]
    except Exception:  # noqa: BLE001
        return None
    if isinstance(vec, list) and vec:
        try:
            return float(vec[0])
        except (TypeError, ValueError):
            return None
    return None


def city_by_id(obs: dict, city_id):
    """Запись своего города по id (ключи живого наблюдения — int)."""
    cities = (obs or {}).get("city")
    if not isinstance(cities, dict):
        return None
    for key in (city_id, str(city_id)):
        rec = cities.get(key)
        if isinstance(rec, dict):
            return rec
    return None


def city_at(obs: dict, x, y):
    """Запись города, стоящего на клетке (x, y): нужно для `join_city`, где актёр —
    юнит, а не город."""
    cities = (obs or {}).get("city")
    if not isinstance(cities, dict):
        return None
    for rec in cities.values():
        if not isinstance(rec, dict):
            continue
        if int(rec.get("x", -1)) == int(x) and int(rec.get("y", -1)) == int(y):
            return rec
    return None


def food_cost_of(obs: dict, default: float = DEFAULT_FOOD_COST) -> float:
    """`food_cost` из правил мира; при отсутствии — измеренное значение по умолчанию."""
    rules = (obs or {}).get("rules")
    if isinstance(rules, dict):
        value = rules.get("food_cost")
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    return float(default)


def allow_swap(city_id, offset, *, food_after: float, size: float = 1.0,
               food_cost: float = 2.0) -> None:
    """§13.432: разрешить снятие жителя, если оно — половина ОБМЕНА «снять плохую → занять лучшую».

    Правило F смотрит на одно действие и потому запрещает снять клетку с едой у города с нулевым
    избытком — то есть запрещает ЛЮБОЙ обмен, и город навсегда остаётся на плохой клетке (замер
    §13.431: наши города размера 1 работали Forest с едой 1, имея рядом свою же Grassland с едой 2).
    Здесь разрешение выдаёт наш управляющий (`brain/ai_default/worker_manager.py`) вместе с
    доказательством: каким станет избыток еды ПОСЛЕ обмена. Оно живёт один ход.
    """
    _SWAP_ALLOWANCE[str(city_id)] = (tuple(offset), float(food_after), float(size), float(food_cost))


def swap_allowed(city_id, offset, *, surplus: float) -> bool:
    """Проверить и снять разрешение обмена для города и клетки."""
    rec = _SWAP_ALLOWANCE.get(str(city_id))
    if not rec:
        return False
    off, food_after, _size, _fc = rec
    if tuple(offset) != tuple(off):
        return False
    _SWAP_ALLOWANCE.pop(str(city_id), None)
    return float(food_after) >= 0.0 or float(surplus) < 0.0


def _offset(name: str):
    """Смещение `(dx, dy)` из имени `city_<family>_<idx>_<dx>_<dy>`."""
    parts = str(name).split("_")
    try:
        return int(parts[-2]), int(parts[-1])
    except (TypeError, ValueError, IndexError):
        return None


def denies(name: str, *, city=None, obs: dict | None = None,
           food_cost: float | None = None, surplus_food=None,
           max_tile_food: float = MAX_TILE_FOOD,
           turn: int | None = None) -> tuple[bool, str]:
    """Запретить ли действие по Правилу F. Возвращает `(запретить, причина)`.

    ``city`` — запись города-цели (для `city_unwork`/`city_change_specialist` это
    город-актёр, для `join_city` — город, куда входит юнит). Если записи нет,
    запрет не выносится: правило работает по ФАКТУ мира, а не по догадке, и
    отсутствие данных не выдаётся за минус (в отчёте это видно как отсутствие отказа —
    такие случаи считает вызывающая сторона).
    """
    text = str(name or "")
    if not city:
        return False, ""
    surplus = city.get("surplus_food") if surplus_food is None else surplus_food
    if surplus is None:
        return False, ""
    surplus = float(surplus)
    if food_cost is None:
        food_cost = food_cost_of(obs or {})

    if text.startswith(UNWORK):
        off = _offset(text)
        if off is None:
            return False, ""
        # §13.432: обмен «снять плохую → занять лучшую» — разрешение выдано управляющим с
        # доказательством избытка ПОСЛЕ обмена; иначе правило F запрещало бы любой обмен.
        if swap_allowed(city.get("id"), off, surplus=surplus):
            _note({"turn": turn, "name": text, "surplus": surplus, "swap": True, "deny": False})
            return False, ""
        cx, cy = city.get("x"), city.get("y")
        tf = tile_food(obs or {}, (cx or 0) + off[0], (cy or 0) + off[1]) \
            if cx is not None and cy is not None else None
        # Если еду клетки не видно — берём наибольшую измеренную: незнание не
        # выдаётся за безопасность.
        known = tf is not None
        loss = float(tf) if known else float(max_tile_food)
        deny = surplus < loss
        _note({"turn": turn, "name": text, "surplus": surplus, "loss": loss,
               "deny": bool(deny), "bound": not known})
        if deny:
            family = "city_unwork"
            example = (f"{text}: surplus={surplus:g} < еда_клетки="
                       f"{loss:g}{'' if known else ' (не видно — граница)'}")
            _tally(family, example)
            return True, f"правило F: {example} — город не прокормит себя"
        return False, ""

    if text.startswith(SPECIALIST):
        _note({"turn": turn, "name": text, "surplus": surplus,
               "loss": float(max_tile_food), "deny": surplus < float(max_tile_food),
               "bound": True})
        if surplus < float(max_tile_food):
            example = (f"{text}: surplus={surplus:g} < {float(max_tile_food):g} "
                       f"(наибольшая измеренная еда клетки)")
            _tally("city_change_specialist", example)
            return True, f"правило F: {example} — цена перевода жителя неизвестна"
        return False, ""

    if text == JOIN:
        _note({"turn": turn, "name": text, "surplus": surplus,
               "loss": float(food_cost), "deny": surplus < float(food_cost),
               "bound": False})
        if surplus < float(food_cost):
            example = (f"{text}: surplus={surplus:g} < food_cost={float(food_cost):g} "
                       f"(размер {city.get('size')})")
            _tally("join_city", example)
            return True, f"правило F: {example} — новый житель не прокормится"
        return False, ""

    return False, ""