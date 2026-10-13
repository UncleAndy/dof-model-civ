"""Оценка клетки города перенесённым числом, когда своих чисел нет (§13.292).

Зачем. У нашего `_tile_score_of` для клеток города чисел не было вовсе: он брал их из
контекста прогноза (`ctx.tile_scores`), а при `--no-dof` прогноз не строится. Измеренный
итог — «в его числах не значится (строк 0)» на `city_unwork_9_-2_0`, кандидат отбрасывался, и
горожанин оставался заперт на плохой клетке (13.290).

Что здесь. Оценка клетки перенесённым числом встроенного ИИ:

* выходы клетки — `brain/ai_default/tile_outputs.tile_outputs_from_rules` (основа рельефа +
  эффекты улучшений, всё из правил мира);
* ценность — `brain/ai_default/values.city_tile_value` (`infracache.c:293`, веса 30/17/18).

Два действия и два разных вопроса — как и в его коде:

* `city_unwork_<idx>_<dx>_<dy>` — снять жителя с клетки, центр города плюс смещение. Снятие
  само по себе выигрыша не даёт, но ОТКРЫВАЕТ ход: у клиента `city_work` недействителен,
  пока нет свободного горожанина (`city/city_actions.py:150`). Поэтому ценность снятия
  сравнивается со СВОБОДНЫМИ клетками радиуса: снимать стоит только плохую клетку.
* `city_work_<idx>_<dx>_<dy>` — поставить жителя на клетку: чем ценнее клетка, тем лучше.

Порядок «снять плохую → занять лучшую» — его, не наш.
"""

from __future__ import annotations

from brain.ai_default.tile_outputs import tile_outputs_from_rules
from brain.ai_default.values import city_tile_value

_UNWORK = "city_unwork_"
_WORK = "city_work_"


def parse_city_tile_action(action_name: str) -> tuple[int, int, int] | None:
    """Разобрать `city_(un)work_<idx>_<dx>_<dy>` → `(индекс, dx, dy)` или None.

    Формат задан авторитетом — клиентом: `city_actions.py:127` (`_%i_%i_%i` = индекс, dx, dy).
    """
    name = str(action_name or "")
    for prefix in (_UNWORK, _WORK):
        if name.startswith(prefix):
            tail = name[len(prefix):]
            parts = tail.split("_")
            if len(parts) != 3:
                return None
            try:
                return int(parts[0]), int(parts[1]), int(parts[2])
            except ValueError:
                return None
    return None


def tile_value_from_rules(terrain, extras) -> float | None:
    """Ценность клетки по правилам мира — или None, если террейн неизвестен.

    None, а не нули: неизвестный террейн не должен выглядеть как клетка без выходов.
    """
    outputs = tile_outputs_from_rules(terrain, extras)
    if outputs is None:
        return None
    return city_tile_value(*outputs)


def unwork_gain(worked_value: float | None, free_values) -> float:
    """Выигрыш от снятия жителя с клетки ценности `worked_value`.

    Снятие стоит хода и само выигрыша не даёт: оно окупается только тем, что освобождает
    горожанина под ЛУЧШУЮ свободную клетку. Поэтому выигрыш = лучшая свободная минус снимаемая,
    и он отрицателен (то есть ход не стоит делать), если снимаемая клетка не хуже свободных.
    """
    if worked_value is None:
        return 0.0
    known = [float(v) for v in free_values if v is not None]
    if not known:
        return 0.0
    return max(0.0, max(known) - float(worked_value))


def work_gain(tile_value: float | None, current_best: float | None) -> float:
    """Выигрыш постановки жителя на клетку: её ценность минус то, что уже занято лучше всех."""
    if tile_value is None:
        return 0.0
    if current_best is None:
        return float(tile_value)
    return max(0.0, float(tile_value) - float(current_best))

#: Смещения клеток, которые город может обрабатывать. Правило движка: клетка входит в
#: городскую карту, если её КВАДРАТ расстояния не больше `city_radius_sq`
#: (`common/map.c:628` — для не-гексов `dx*dx + dy*dy`; условие `dr <= sq_radius` —
#: `common/map.h:397`). Порядок — по квадрату расстояния, затем по dy, dx: при равной
#: ценности выбор становится воспроизводимым, а не зависящим от порядка перебора.
def workable_offsets(radius_sq: int) -> list[tuple[int, int]]:
    """Смещения клеток городского радиуса по правилу движка, ближние первыми."""
    try:
        limit = int(radius_sq)
    except (TypeError, ValueError):
        return [(0, 0)]
    if limit < 0:
        return [(0, 0)]
    side = int(limit ** 0.5) + 1
    out = []
    for dy in range(-side, side + 1):
        for dx in range(-side, side + 1):
            dr = dx * dx + dy * dy
            if dr <= limit:
                out.append((dr, dy, dx))
    out.sort()
    return [(dx, dy) for _dr, dy, dx in out]

