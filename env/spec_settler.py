"""Семейство ценности города-творца — порт из ветки `v2` (§10.116, §10.108).

В `v2` ценность посчитана так (`brain/v2/horizon.py:256`):

    gain = ln(DoF города) × frac × cover − C_pop − цена_смены

где `frac = min(1, H/eta)`, `cover` — доля выживания под ударом (прикрытие своей армией),
`C_pop` — цена жителя (поселенец стоит 2 населения), `цена_смены` — потеря вложенных щитов
(§10.102, канал `env/switch_channel.py`).

**Валюта — счёт, а не нормированный DoF.** `ln` применяется к СЧЁТУ возможностей (> 1), как
в `v2` (`dof_of`) и в счёте `v0.11` (`env/entity_extractor.measured_dof`: `Σ ln(dof_count)`).
Нормированный `current_dof ∈ [0, 1]` — другая величина: `ln` от неё ≤ 0 и дал бы **премию за
отказ**. Поэтому нормированное значение отвергается с причиной, а не считается.

**Абляция помнится кодом, а не комментарием.** Форма «без `frac`» в `v2` испытана и отвергнута
(вытесняла военную постройку целиком, A 0 военных, 5/10 против B 8/10). Здесь `frac`
применяется всегда, а отвергнутая форма живёт отдельной функцией `city_maker_value_rejected`
для сверки с записями — выбрать её случайно нельзя.

**Опорные точки без свободных чисел.** `spacing = min(1, max(0, (d − 1)/(CITY_SPACING − 1)))`:
под своим городом поселенец почти бесполезен (делит работную зону), на дистанции `CITY_SPACING`
ценен полностью. Числа взяты из `v2` вместе с их смыслом, а не подобраны.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

#: Целевой разнос городов (`v2`, §10.108): ближе — поселенец дешевеет.
CITY_SPACING: int = 6

#: Сколько населения стоит поселенец — ИЗ ПРАВИЛ МИРА, а не из чужого набора.
#: Прочитано в правилах стенда: `classic/units.ruleset`, набор `[unit_settlers]`,
#: строка `pop_cost = 1` (рядом `name = _("Settlers")`). Прежде здесь стояло 2 —
#: это значение набора civ2civ3, а стенд играет на classic, то есть факт модели был
#: взят из чужого мира. Цена поселенца от этого была завышена вдвое.
SETTLER_POP_COST: int = 1


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def _dof_at(size: Any, dof_by_size: Optional[Mapping[Any, Any]]) -> tuple[Optional[float], str]:
    """Счёт DoF для размера города: измеренный, иначе СРЕДНЕЕ по известным размерам.

    Средним, а не нулём: нуль был бы утверждением «город без возможностей», а мы просто
    не измеряли этот размер (правило владельца модели: незнание ≠ отсутствие возможностей).
    """
    if not isinstance(dof_by_size, Mapping) or not dof_by_size:
        return None, "счёт DoF по размерам города не измерен"
    wanted = {int(k): _as_float(v) for k, v in dof_by_size.items()
              if _as_float(v) is not None}
    if not wanted:
        return None, "счёт DoF по размерам города не измерен"
    try:
        key = int(size)
    except (TypeError, ValueError):
        key = None
    if key is not None and key in wanted:
        return wanted[key], f"размер {key} измерен: {wanted[key]:g}"
    mean = sum(wanted.values()) / float(len(wanted))
    return mean, (f"размер {size} не измерен — среднее по известным ({len(wanted)}): "
                  f"{mean:g}")


def population_cost(size: Any, dof_by_size: Optional[Mapping[Any, Any]],
                    pop_cost: int = SETTLER_POP_COST) -> tuple[float, str]:
    """Цена жителя: `ln(DoF(s)) − ln(DoF(s − 2))` — город становится меньше.

    Малый город платит дорого, крупный почти ничего. Числа не годятся (нет счёта, размер
    не больше цены) — 0 **с причиной**: цена жителя не выдумывается.
    """
    try:
        now_size = max(1, int(size))
    except (TypeError, ValueError):
        return 0.0, "размер города не назван — цена жителя не считается"
    after_size = max(1, now_size - int(pop_cost))
    d_now, src_now = _dof_at(now_size, dof_by_size)
    d_after, src_after = _dof_at(after_size, dof_by_size)
    if d_now is None or d_after is None:
        return 0.0, f"цена жителя не считается: {src_now if d_now is None else src_after}"
    if d_now <= 0.0 or d_after <= 0.0 or d_now <= d_after:
        return 0.0, (f"цена жителя нулевая с причиной: размер {now_size}→{after_size} даёт "
                     f"{d_now:g}→{d_after:g} (уменьшения счёта не видно)")
    value = math.log(d_now) - math.log(d_after)
    return value, (f"цена жителя: размер {now_size}→{after_size}, счёт {d_now:g}→{d_after:g} "
                   f"({src_now}; {src_after}) → −{value:.3f}")


def cover_factor(risk: Optional[Any], index: Optional[Any]) -> tuple[float, str]:
    """Доля выживания под ударом: `max(0, 1 − риск/индекс)`, иначе 1.

    Риск не измерен — 1 **с причиной** («прикрытие не учитывается»), а не ноль: ноль
    означал бы «поселенца не довести» ровно потому, что мы не знаем риска. Источник риска
    (§10.111–115: цена удара, доля империи под ударом) — следующий пункт порта, и пока его
    нет, причина так и называется.
    """
    r, idx = _as_float(risk), _as_float(index)
    if r is None or idx is None:
        return 1.0, "риск под ударом не измерен — прикрытие армией не учитывается (×1.00)"
    if idx <= 0.0:
        return 1.0, f"индекс {idx:g} — долю риска считать не от чего (×1.00)"
    cover = max(0.0, 1.0 - (r / idx))
    return cover, f"доля выживания под ударом: 1 − риск {r:g}/индекс {idx:g} = ×{cover:.2f}"


def spacing_factor(distance: Optional[Any]) -> tuple[float, str]:
    """Множитель близости к своему городу (§10.108): `min(1, max(0, (d−1)/(CITY_SPACING−1)))`."""
    d = _as_float(distance)
    if d is None:
        return 1.0, "дистанция до своего города не измерена — множитель ×1.00"
    factor = min(1.0, max(0.0, (d - 1.0) / float(CITY_SPACING - 1)))
    return factor, (f"близость к городу: дистанция {d:g} → множитель ×{factor:.2f} "
                    f"(под городом ~0, на {CITY_SPACING} — полная)")


def torus_distance(x0: Any, y0: Any, x1: Any, y1: Any,
                   xsize: Optional[Any] = None) -> Optional[float]:
    """Евклидова дистанция, по X — тороидальная (`v2`: `_nearest_own_city_dist`)."""
    vals = [_as_float(v) for v in (x0, y0, x1, y1)]
    if any(v is None for v in vals):
        return None
    ax0, ay0, ax1, ay1 = vals
    dx = abs(ax0 - ax1)
    size = _as_float(xsize)
    if size and size > 0:
        dx = min(dx, abs(size - dx))
    return math.hypot(dx, ay1 - ay0)


def uncrowding_gain(distance_before: Any, distance_after: Any) -> tuple[float, str]:
    """Выигрыш от ухода прочь от города: `ln(f_после) − ln(f_до)` — без свободных чисел.

    База (счёт поселенца) в логарифме отношения сокращается, поэтому выигрыш не зависит от
    того, насколько велик сам поселенец: он равен `ln(f_after / f_before)`.
    """
    f_before, why_before = spacing_factor(distance_before)
    f_after, why_after = spacing_factor(distance_after)
    if f_after <= f_before:
        return 0.0, f"не удаляемся: {why_before}; {why_after}"
    return (math.log(f_after) - math.log(f_before),
            f"уход от города {distance_before}→{distance_after}: ×{f_before:.2f}→×{f_after:.2f} "
            f"→ +{math.log(f_after) - math.log(f_before):.3f}")


def city_maker_value(city_dof: Any, eta: Any, horizon: Any,
                     risk: Optional[Any] = None, index: Optional[Any] = None,
                     size: Optional[Any] = None,
                     dof_by_size: Optional[Mapping[Any, Any]] = None,
                     switch_loss: Optional[Any] = None) -> tuple[Optional[float], str]:
    """Ценность города-творца: `ln(счёт города) × frac × cover − C_pop − цена_смены`.

    Каждый множитель возвращает свою причину, и причина видна целиком: без этого «две трети
    ценности» невозможно защитить перед владельцем модели. `city_dof` — СЧЁТ (> 1);
    нормированный `current_dof ≤ 1` отвергается с причиной.
    """
    count = _as_float(city_dof)
    if count is None:
        return None, "счёт DoF создаваемого города не измерен — ценность не считается"
    if count <= 1.0:
        return None, (f"передан нормированный DoF ({count:g} ≤ 1), а нужен СЧЁТ: ln от него "
                      f"≤ 0 дал бы премию за отказ от постройки")
    try:
        eta_value = max(1e-9, float(eta))
    except (TypeError, ValueError):
        return None, "срок постройки не назван — ценность не считается"
    h = _as_float(horizon)
    if h is None:
        return None, "горизонт прогноза не назван — ценность не считается"
    frac = min(1.0, h / eta_value)
    cover, why_cover = cover_factor(risk, index)
    base = math.log(count) * frac * cover
    c_pop, why_pop = population_cost(size, dof_by_size) if size is not None else (0.0, "")
    parts = [f"ln(счёт {count:g}) × frac {frac:.3f} × cover {cover:.2f} = {base:.3f}"]
    if why_pop:
        parts.append(why_pop)
    value = base - c_pop
    loss = _as_float(switch_loss)
    if loss is not None and loss > 0.0:
        value -= loss
        parts.append(f"цена смены −{loss:g} (разово, §10.102)")
    if why_cover and cover == 1.0:
        parts.append(why_cover)
    return value, "; ".join(parts) + f" → итог {value:.3f}"


def city_maker_value_rejected(city_dof: Any) -> tuple[Optional[float], str]:
    """ОТВЕРГНУТАЯ абляцией форма (`v2`, §10.116): `ln(счёт)` без `frac`.

    Живёт отдельно и называется вслух: без `frac` поселенец поднимается над воином и
    вытесняет военную постройку целиком. Функция — предупреждение и число для сверки
    с записями `v2` (там это 3.091), а не вариант выбора.
    """
    count = _as_float(city_dof)
    if count is None or count <= 0.0:
        return None, "счёт DoF города не измерен"
    return math.log(count), (f"ln({count:g}) = {math.log(count):.3f} — форма БЕЗ frac "
                             f"(абляция §10.116 — отвергнута, вытесняет военную постройку)")
