"""Опасность и военная нужда города — перенос из встроенного ИИ.

Источник (закреплённый коммит `14b7a645a74155d4f3dd300221c5b4f0ffca8fe8`):

* `ai/default/daimilitary.c:519` `assess_danger_unit` — сколько опасности несёт **один**
  видимый чужой юнит: он должен УМЕТЬ дойти до города (`move_time` конечен) и уметь
  напасть на него; ценность — `adv_unit_att_rating`, поправленная бонусами атаки и
  защиты: `danger * (amod + 100) / MAX(dmod, 1)`.
* `ai/default/daimilitary.c:683` `assess_danger` — сумма по видимым юнитам; горизонт
  `assess_turns = 3` (`:798-802`: 2 при гандикапе `H_ASSESS_DANGER_LIMITED`, 6 для
  «cpu hog»). Его слова: «Urgency — число враждебных юнитов, способных напасть за три
  хода; grave danger — за один».
* `ai/default/daimilitary.c:1955-1962` — **ранний отказ** военного советника:
  `surplus[O_SHIELD] <= 0`, либо недовольных больше, чем даёт эффект, либо это город
  чудес («Things we consider below are not life-saving»).
* `ai/default/daimilitary.c:1826` — главное условие: защитники нужны только при
  `danger != 0 || martial_value > 0`. Без нужды советник возвращает ПУСТОЙ выбор, и
  город не строит войск вовсе. Его же комментарий о причине: «Changing to quadratic
  to stop AI from building piles of small units».

Чего мир не публикует и чем это заменено — правило владельца «неизвестное моделировать
средним по известным, НЕ нулём»:

* паспорта чужого юнита нет (виден только владелец клетки на карте), поэтому его атака
  берётся средним по известным типам (`spec_threat.mean_attack`);
* его скорость — средним (`spec_threat.mean_move_rate`);
* бонусы атаки и защиты (`amod`, `dmod`) не публикуются → берём 0, то есть множитель
  `(0 + 100) / MAX(0 + 100, 1) = 1`; вклад бонусов не выдумываем;
* путь до города — не карта путей (`pf_reverse_map`), а чебышёвское расстояние по клеткам,
  делённое на среднюю скорость. Это НИЖНЯЯ оценка времени (препятствия его только
  увеличивают), и она названа в следе, а не выдана за его расчёт.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

# Его горизонт оценки (`daimilitary.c:798-802`, без гандикапов).
ASSESS_TURNS = 3
# Его определение urgency и grave danger (`daimilitary.c:678-680`).
URGENCY_TURNS = 3
GRAVE_TURNS = 1


def is_military(name: str) -> bool:
    """Боевой ли это род — по ФЛАГУ МИРА `NonMil`, а не по силам.

    По силам не отличить: у поселенцев защита 1, у рабочих тоже, поэтому признак
    «атака или защита больше нуля» объявил бы поселенцев боевыми и придержал бы их
    выдачу. Мир сам называет род мирным — флагом `NonMil` (`UTYF_NONMIL`), и его
    советник боевые роды берёт только там, где силы есть (`dai_choose_bodyguard`,
    `dai_choose_attacker`), а поселенцы, рабочие, дипломаты и караваны проходят
    другими путями (`daisettler.c`, `dai_choose_diplomat_*`).
    """
    try:
        from env.rules_costs import UNIT_STATS
    except Exception:  # noqa: BLE001
        return False
    row = UNIT_STATS.get(str(name))
    if not isinstance(row, Mapping):
        return False
    try:
        if "NonMil" in tuple(row.get("flags") or ()):
            return False
    except TypeError:
        pass
    for key in ("attack", "defense"):
        try:
            if float(row.get(key) or 0.0) > 0.0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _tile_of(city_rec: Mapping[str, Any]) -> tuple[int, int] | None:
    try:
        return int(city_rec.get("x")), int(city_rec.get("y"))
    except (TypeError, ValueError):
        return None


def assess_danger(city_rec: Mapping[str, Any], obs: Mapping[str, Any],
                  my_player_id: Any = 0) -> dict[str, Any]:
    """Его оценка опасности города по видимым чужим юнитам.

    Возвращает `danger` (сумма вкладов), `urgency` (число юнитов, способных напасть за
    `URGENCY_TURNS` ходов), `grave` (за `GRAVE_TURNS`), `units` (сколько чужих клеток
    видно), а также основу средних (`mean_attack`, `mean_move`) — чтобы у вызывающего
    была видна ОСНОВА числа, а не только итог.
    """
    out: dict[str, Any] = {"danger": 0.0, "urgency": 0, "grave": 0, "units": 0,
                           "mean_attack": None, "mean_move": None, "note": ""}
    tile = _tile_of(city_rec)
    if tile is None:
        out["note"] = "у записи города нет клетки — опасность не считаем"
        return out
    try:
        from env import spec_threat
        foreign = spec_threat.foreign_units_from_map(obs, my_player_id)
        mean_attack, n_attack = spec_threat.mean_attack(obs, my_player_id)
        mean_move, n_move = spec_threat.mean_move_rate(obs, my_player_id)
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"источник чужих юнитов недоступен: {type(exc).__name__}"
        return out
    out["units"] = len(foreign)
    out["mean_attack"] = mean_attack
    out["mean_move"] = mean_move
    # §13.418: ЕГО ПЕРВАЯ проверка перед перебором юнитов — `adv_is_player_dangerous`
    # (`server/advisors/advdata.c:1103`): опасен только тот, с кем война (`DS_WAR`) или перемирие
    # (`DS_CEASEFIRE`), либо у кого есть повод расторгнуть договор (`has_reason_to_cancel > 0`).
    # Замер r980: у всех сторон «Never met», а мы считали их опасными и держали 10 `Warriors`
    # против НУЛЯ военных у каждой стороны-ИИ. Отношения берём из сейва; нет сведений (`None`) —
    # оставляем как было: «незнание ≠ отсутствие возможностей».
    try:
        from env.diplomacy_from_save import dangerous_now as _dangerous_now
        _allowed = _dangerous_now(int(my_player_id))
    except Exception:  # noqa: BLE001
        _allowed = None
    if _allowed is not None:
        foreign = [f for f in foreign if int(f[0]) in _allowed]
        out["units"] = len(foreign)
        out["dangerous_players"] = sorted(_allowed)
    if not foreign:
        out["note"] = ("опасных чужих юнитов не видно — опасность 0 (его же умолчание)"
                       if _allowed is not None else
                       "чужих юнитов на карте не видно — опасность 0 (его же умолчание)")
        return out
    if mean_attack is None:
        # Известных боевых типов нет вовсе — «нечего усреднять», а не «безобиден».
        out["note"] = "нет известных типов с атакой — силу чужого оценить нечем"
        return out
    move = float(mean_move) if mean_move else 1.0
    move = max(move, 1.0)
    cx, cy = tile
    total = 0.0
    urgency = grave = 0
    for _owner, x, y in foreign:
        dist = max(abs(int(x) - cx), abs(int(y) - cy))
        turns = max(1, int(math.ceil(dist / move)))
        if turns > ASSESS_TURNS:
            continue
        total += float(mean_attack)   # бонусы (amod, dmod) не публикуются → множитель 1
        if turns <= URGENCY_TURNS:
            urgency += 1
        if turns <= GRAVE_TURNS:
            grave += 1
    out["danger"] = total
    out["urgency"] = urgency
    out["grave"] = grave
    out["note"] = (f"чебышёвское расстояние / среднюю скорость {move:.2f}; "
                   f"бонусов нет → множитель 1")
    return out


def military_need(city_rec: Mapping[str, Any], obs: Mapping[str, Any],
                  my_player_id: Any = 0, shields: float | None = None
                  ) -> tuple[bool, str, dict[str, Any]]:
    """Можно ли вообще рассматривать боевой род в этом городе.

    Возвращает `(нужно, причина, опасность)`. Правила — его, порядок его:
    сначала ранний отказ советника (`daimilitary.c:1955`), потом условие нужды
    (`:1826`). `shields` — выход города по щитам (`prod_shield`), если известен.
    """
    danger = assess_danger(city_rec, obs, my_player_id)
    if shields is not None:
        try:
            if float(shields) <= 0.0:
                return False, "выход города по щитам <= 0 — его ранний отказ", danger
        except (TypeError, ValueError):
            pass
    if danger["danger"] > 0.0:
        return True, (f"опасность {danger['danger']:.2f} по {danger['urgency']} юнитам "
                      f"в пределах {URGENCY_TURNS} ходов"), danger
    return False, f"опасности нет ({danger['note']}) — его умолчание: войск не просим", danger
