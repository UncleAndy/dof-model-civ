"""Цена угрозы под `v0.11` — порт из ветки `v2` (`brain/v2/threat.py`, §10.111–10.115).

Зачем это вообще. В `v2` измерено (§10.69): агент терял всё — 0 городов, 0 юнитов. Это слепота
модели, а не неудача политики: индекс `Σ ln(DoF)` не имеет цены за приближение сущности к нулю,
поэтому в нём нет ни одного защитного действия. Здесь эта цена появляется.

**Объявленные правила (те же, что в `v2`, перенесены как правила, не как числа):**

* **T1. Угроза — только наблюдённое нападение.** Мирный чужой не угроза: он обычная сущность и
  ПЛЮСУЕТСЯ к общему DoF. Близость боеспособного соседа нападением не является («догадка из
  тумана нападением не считается»). Поэтому до первого наблюдённого нападения список угроз пуст,
  и цена риска равна нулю не потому, что опасности нет, а потому что **нападения ещё не было**.
* **T2. Досягаемость** — расстояние Чебышёва с замыканием по X (карта-цилиндр), делённое на
  опубликованную скорость угрозы; ходов ≤ τ ⇒ наша сущность **под ударом**.
* **T3. Цена риска** — сумма `ln(DoF)` наших сущностей под ударом: миникас (аксиома 5), без
  выдуманных вероятностей — берётся худший случай.
* **T4. Ценность защиты** — уменьшение этой цены.
* **T5. Происхождение** — «выведено (миникас по наблюдённой угрозе)»: это не замер потери, а
  расчёт по измеренным расстояниям, скоростям и угрозам. В протоколе помечается явно.

**ОКНО УДАРА — 1 ход, и вот почему** (`v2`, измерено): при сроке 5.8 и скорости угрозы 3
досягаемость ≈17 клеток, то есть «под ударом» оказывается почти вся карта, и сигнал угрозы
перестаёт что-либо различать (цена одинакова везде, а уход на три шага всё равно «под ударом»).
Это отказ от величины, которая не различает, а не подгонка.

**Потенциальный источник** (`v²`, задано владельцем модели, §10.111): чужой НА НАШЕЙ территории у
города делает город условно уязвимым, и цена этого — доля `POTENTIAL_FACTOR` от полной цены. Полная
цена (источник коллапса) остаётся за наблюдённое нападение. Мирный чужой при этом НЕ становится
угрозой T1: он даёт мотив прикрыть город, но не цену риска потери.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Optional, Sequence

from env import spec_threat as T

#: Окно удара: за сколько ходов удар может состояться (§10.111, отказ от неразличающей величины).
STRIKE_TURNS: float = 1.0

#: Доля полной цены для «потенциального источника» — чужого на нашей территории (задано: не ниже 0.8).
POTENTIAL_FACTOR: float = 0.8


def cheb_wrapped(ax: Any, ay: Any, bx: Any, by: Any,
                 xsize: Optional[Any] = None) -> Optional[int]:
    """Расстояние Чебышёва, по X — с замыканием (карта-цилиндр)."""
    vals = []
    for v in (ax, ay, bx, by):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        vals.append(float(v))
    x0, y0, x1, y1 = vals
    dx = abs(x0 - x1)
    if isinstance(xsize, (int, float)) and not isinstance(xsize, bool) and xsize > 0:
        dx = min(dx, abs(float(xsize) - dx))
    return int(max(dx, abs(y0 - y1)))


def _published_specs(obs: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Опубликованный каталог типов: `sup_units`/`sup_improvements` в записях технологий."""
    out: list[Mapping[str, Any]] = []
    for tech in ((obs or {}).get("tech") or {}).values():
        if not isinstance(tech, Mapping):
            continue
        for key in ("sup_units", "sup_improvements"):
            for spec in (tech.get(key) or []):
                if isinstance(spec, Mapping):
                    out.append(spec)
    return out


def mean_move_rate(obs: Mapping[str, Any]) -> tuple[Optional[float], int]:
    """Средняя скорость по ПУБЛИКУЕМОМУ каталогу типов и их число.

    Скорость чужого без паспорта берётся средним по известным, а не единицей «по умолчанию»:
    единица была бы утверждением «он медленный» ровно потому, что мы о нём ничего не знаем.
    """
    seen: list[float] = []
    for spec in _published_specs(obs):
        raw = spec.get("move_rate", spec.get("type_move_rate"))
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and float(raw) > 0:
            seen.append(float(raw))
    if not seen:
        return None, 0
    return sum(seen) / float(len(seen)), len(seen)


def move_rate_of(obs: Mapping[str, Any], spec: Optional[Mapping[str, Any]] = None,
                 fallback: float = 1.0) -> tuple[float, str]:
    """Скорость угрозы: паспорт типа, иначе среднее по каталогу, иначе объявленный запасной 1."""
    if isinstance(spec, Mapping):
        raw = spec.get("move_rate", spec.get("type_move_rate"))
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and float(raw) > 0:
            return float(raw), f"измерено (паспорт типа): {float(raw):g}"
    mean, n = mean_move_rate(obs)
    if mean is not None:
        return mean, f"выведено: среднее по {n} опубликованным типам ({mean:g})"
    return float(fallback), (f"скорость неизвестна и каталог пуст — берётся {float(fallback):g} "
                             f"как объявленный запасной, а не как измерение")


def threats(obs: Mapping[str, Any], marks: Any, turn: Any,
            my_player_id: Any = 0) -> list[dict[str, Any]]:
    """T1: угрозы — только те, чьё нападение НАБЛЮДЕНО (метки из `env.spec_attack`).

    Позиция берётся только если источник виден В ТЕКУЩЕМ наблюдении (карта `map.unit_owner`):
    сущность остаётся источником (метка держится горизонт), но по устаревшим координатам не
    считается — иначе мы «видели бы» нападающего там, где его давно нет.
    """
    if marks is None:
        return []
    active = marks.active(turn) if hasattr(marks, "active") else {}
    if not active:
        return []
    by_owner: dict[int, list[tuple[int, int]]] = {}
    for owner, x, y in T.foreign_units_from_map(obs, my_player_id):
        by_owner.setdefault(int(owner), []).append((int(x), int(y)))
    out: list[dict[str, Any]] = []
    for eid, info in active.items():
        owner = info.get("owner")
        if owner is None:
            continue
        for (x, y) in by_owner.get(int(owner), []):
            attack, origin = T.mean_attack(obs, my_player_id)
            rate, rate_origin = move_rate_of(obs)
            out.append({"entity": str(eid), "owner": int(owner), "x": x, "y": y,
                        "attack": attack, "attack_origin": origin,
                        "move_rate": rate, "move_rate_origin": rate_origin,
                        "since_turn": info.get("turn"), "why": info.get("why")})
    return out


def exposure(obs: Mapping[str, Any], marks: Any, turn: Any, my_player_id: Any = 0,
             tau: float = STRIKE_TURNS) -> dict[str, dict[str, Any]]:
    """T2: наши сущности под ударом → чем и за сколько ходов (ближайшая угроза побеждает).

    Учитываются и юниты, и города: у города цена потери — его слагаемое `ln(DoF)`.
    """
    xsize = ((obs or {}).get("map") or {}).get("xsize")
    found = threats(obs, marks, turn, my_player_id)
    if not found:
        return {}
    our: list[tuple[str, Any, Any]] = []
    for kind, section in (("unit", (obs or {}).get("unit")), ("city", (obs or {}).get("city"))):
        for key, rec in (section.items() if isinstance(section, Mapping) else ()):
            if not isinstance(rec, Mapping):
                continue
            if int(rec.get("owner", my_player_id) or my_player_id) != int(my_player_id):
                continue
            our.append((f"{kind}_{key}", rec.get("x"), rec.get("y")))
    out: dict[str, dict[str, Any]] = {}
    for eid, x, y in our:
        for threat in found:
            tiles = cheb_wrapped(x, y, threat["x"], threat["y"], xsize)
            if tiles is None:
                continue
            turns = tiles / float(max(1.0, threat["move_rate"]))
            if turns <= float(tau):
                prev = out.get(eid)
                if prev is None or turns < prev["turns"]:
                    out[eid] = {"threat": threat["entity"], "owner": threat["owner"],
                                "tiles": tiles, "turns": round(turns, 1),
                                "attack": threat["attack"]}
    return out


def risk_price(exposure_map: Mapping[str, Mapping[str, Any]],
               dof_by_entity: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    """T3: цена риска — сумма `ln(DoF)` наших сущностей под ударом (миникас, худший случай).

    Счёт берётся только там, где он ИЗМЕРЕН (> 0): нечем посчитать — сущность в деталь
    попадает с пометкой, а в цену не входит. Вероятности не выдумываются: удар либо состоится
    (и слагаемое теряется целиком), либо нет — берётся худший случай.
    """
    price = 0.0
    detail: dict[str, Any] = {}
    for eid, info in exposure_map.items():
        raw = dof_by_entity.get(eid)
        count = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
        if count is not None and count > 0.0:
            price += math.log(count)
            detail[eid] = {**dict(info), "dof": count}
        else:
            detail[eid] = {**dict(info), "dof": None,
                           "not_counted": "счёт DoF не измерен — в цену не входит"}
    return price, detail


def city_intruders(obs: Mapping[str, Any], city_id: Any, my_player_id: Any = 0,
                   radius: Optional[Any] = None) -> list[tuple[int, int, int]]:
    """Чужие рядом с НАШИМ городом (радиус города, по умолчанию из `city_radius_sq`).

    Мирный чужой здесь — не угроза T1, а нарушитель территории: он даёт мотив прикрыть город.
    """
    city_sec = (obs or {}).get("city")
    city = city_sec.get(str(city_id)) if isinstance(city_sec, Mapping) else None
    if not isinstance(city, Mapping):
        return []
    xsize = ((obs or {}).get("map") or {}).get("xsize")
    if radius is None:
        rsq = city.get("city_radius_sq")
        radius = int(math.isqrt(int(rsq))) if isinstance(rsq, (int, float)) and rsq >= 0 else 4
    out: list[tuple[int, int, int]] = []
    for owner, x, y in T.foreign_units_from_map(obs, my_player_id):
        tiles = cheb_wrapped(x, y, city.get("x"), city.get("y"), xsize)
        if tiles is not None and tiles <= int(radius):
            out.append((int(owner), int(x), int(y)))
    return out


def cover_price(city_dof: Any, intruders: Sequence[Any],
                factor: float = POTENTIAL_FACTOR) -> tuple[float, str]:
    """Ценность прикрытия города: `POTENTIAL_FACTOR × ln(счёт города)` при нарушителях.

    Нарушителей нет — цена нулевая С ПРИЧИНОЙ («прикрывать не от кого»). Счёт города не
    измерен или ≤ 1 — тоже нуль с причиной: `ln` от нормированного DoF дал бы премию за отказ.
    """
    if not intruders:
        return 0.0, "у города чужих рядом нет — прикрывать не от кого"
    count = float(city_dof) if isinstance(city_dof, (int, float)) and not isinstance(city_dof, bool) else None
    if count is None or count <= 1.0:
        return 0.0, (f"счёт DoF города не измерен или нормирован ({city_dof}) — цена прикрытия "
                     f"не выводится")
    value = float(factor) * math.log(count)
    return value, (f"прикрытие города: нарушителей {len(intruders)} (одному нарушителю один "
                   f"защитник), цена условной угрозы {factor:g} × ln({count:g}) = {value:.3f}")


def risk_with_reason(obs: Mapping[str, Any], marks: Any, turn: Any, my_player_id: Any = 0,
                     dof_by_entity: Optional[Mapping[str, Any]] = None,
                     tau: float = STRIKE_TURNS) -> tuple[float, dict[str, Any], str]:
    """Цена риска ВМЕСТЕ С ПРИЧИНОЙ: «угроз нет» и «угрозы не достают» — разные вещи.

    Без этой разницы ноль читался бы как «опасности нет». У `v2` формулировка была ровно такая:
    цена риска нулевая не потому, что опасности нет, а потому что нападения ещё не было.
    """
    found = threats(obs, marks, turn, my_player_id)
    active = marks.active(turn) if hasattr(marks, "active") else {}
    if not found:
        if active:
            return 0.0, {}, (f"источник коллапса известен ({len(active)}), но в текущем наблюдении "
                             f"не виден: по устаревшим координатам не считаем — «видели бы» там, "
                             f"где его давно нет")
        return 0.0, {}, ("нападения ещё не наблюдалось — угроз нет; цена риска нулевая не потому, "
                         "что опасности нет, а потому что нападения не было")
    exp = exposure(obs, marks, turn, my_player_id, tau)
    if not exp:
        return 0.0, {}, (f"наблюдённых угроз {len(found)}, но ни одна не достаёт до наших сущностей "
                         f"за τ={tau:g} ход(ов): миникас пуст")
    price, detail = risk_price(exp, dof_by_entity or {})
    counted = sum(1 for d in detail.values() if d.get("dof"))
    return price, detail, (f"цена риска {price:.3f}: под ударом {len(exp)} наших сущностей, в цену "
                           f"вошло {counted} — выведено миникасом по наблюдённой угрозе (T5, "
                           f"не замер потери)")


def defensive_value(risk_before: float, risk_after: float) -> tuple[float, str]:
    """T4: ценность защитного действия — насколько падает цена риска."""
    drop = float(risk_before) - float(risk_after)
    if drop <= 0.0:
        return 0.0, (f"цена риска не убывает ({risk_before:g} → {risk_after:g}) — "
                     f"действие не защитное")
    return drop, f"цена риска {risk_before:g} → {risk_after:g} ⇒ сохраняется {drop:.3f}"
