"""Срок постройки — из измеренного, в объявленном порядке источников.

Перенос факта из ветки `v2` (§10.76–10.78 её журнала) под рамку `v0.11`. Мир
публикует `city["turns_to_prod_complete"]` **только для текущего производства**;
для нового варианта публикации нет, и срок добывается объявленным путём:

1. `measured_own_launch` — мы сами запустили `produce_X`, и мир на следующем ходу
   опубликовал срок именно этого варианта (в `v2` это записывалось связью
   `produce_eta`; измерено там же: `Warriors` — 59 замеров, медиана 2 хода);
2. `published_current` — публикация мира для варианта, который уже строится;
3. `derived_price_shields` — вывод из измеренных цены и щитов:
   `max(1, ceil((цена − запас) / щиты за ход))`. Источник помечается
   **выведенным**, а не наблюдённым: он не измерение, а следствие двух измерений;
4. `estimated_mean` — цены и публикации нет: срок моделируется **средним по
   измеренным** (правило владельца модели: «неизвестное моделировать средним по
   известным, НЕ нулём»), и это тоже названо;
5. `unknown` — измерять нечего и усреднять не по чему: `None`, а не ноль.

Цена не выдумывается: она берётся либо из паспорта типа (`build_cost`), либо из
чисел самого города (`env.measured_facts.cost_from_city`: `shield_stock /
prod_process` — измерено, что `prod_process` есть доля готовности, а не выход).
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

#: Объявленный порядок источников: от наблюдённого к выведенному.
ETA_SOURCES: tuple[str, ...] = (
    "measured_own_launch",
    "published_current",
    "derived_price_shields",
    "estimated_mean",
    "unknown",
)


def eta_from_price_and_shields(price: Optional[float],
                               stock: Optional[float],
                               shields_per_turn: Optional[float]) -> Optional[float]:
    """Выведенный срок: `max(1, ceil((цена − запас) / щиты за ход))`.

    Возвращает `None`, если считать нечем (нет цены или щиты нулевые) — незнание,
    а не «один ход»: единица была бы утверждением «постройка мгновенна».
    """
    if price is None or shields_per_turn is None:
        return None
    try:
        price, stock, rate = float(price), float(stock or 0.0), float(shields_per_turn)
    except (TypeError, ValueError):
        return None
    if rate <= 0.0:
        return None
    return float(max(1, math.ceil((price - stock) / rate)))


def build_eta(*, price: Optional[float] = None,
              stock: Optional[float] = 0.0,
              shields_per_turn: Optional[float] = None,
              measured: Optional[float] = None,
              published: Optional[float] = None,
              known_etas: Iterable[float] = ()) -> tuple[Optional[float], str]:
    """Срок постройки и ИМЯ источника (порядок объявлен в `ETA_SOURCES`).

    `measured` — срок, опубликованный миром для варианта, который МЫ запустили;
    `published` — публикация для текущего производства города;
    `known_etas` — измеренные сроки других вариантов (для среднего).
    """
    if measured is not None:
        return float(measured), "measured_own_launch"
    if published is not None:
        return float(published), "published_current"
    derived = eta_from_price_and_shields(price, stock, shields_per_turn)
    if derived is not None:
        return derived, "derived_price_shields"
    known = [float(x) for x in known_etas if x is not None]
    if known:
        return sum(known) / float(len(known)), "estimated_mean"
    return None, "unknown"
