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


#: Потеря щитов при СМЕНЕ варианта постройки. Замер `v2` (§10.102): две партии по
#: 40 ходов, 80 наблюдений — медиана 3, среднее 2.49, максимум 5, нулей 30; щитов до
#: действия медиана 6. То есть смена варианта съедает около половины накопленного.
#: Число измерено в рамке v0.9.1; пока в нашей рамке своего замера нет, оно
#: используется как НАЗВАННАЯ ССЫЛКА, а не как «наше измерение».
SWITCH_LOSS_SHIELDS_MEDIAN: float = 3.0


def menu_is_measured(menu: Iterable[str]) -> bool:
    """Пустое окно меню — это НЕ ИЗМЕРЕНИЕ, а помеха в наблюдении.

    Замер `v2` (§10.88): из 2514 записей меню города **187 (7.4 %)** имели ноль
    переходов — пустое окно («загрязнение»). Читать их как «у города нет действий»
    значило бы посчитать незнание нулём; такие записи исключаются, а не усредняются.
    """
    return len(list(menu)) > 0


def switch_cost_shields(lost_shields: Optional[float] = None,
                        net_shield_gain: Optional[float] = None,
                        current_eta: Optional[float] = None,
                        same_variant: bool = False,
                        loss_median: Optional[float] = SWITCH_LOSS_SHIELDS_MEDIAN
                        ) -> tuple[Optional[float], float, str]:
    """Цена ОТКАЗА от начатой постройки: `(щиты, доля срока, причина)`.

    РАМКИ РАЗНЫЕ, И ЭТО СУЩЕСТВЕННО. В `v2` цена считалась как
    `ln(DoF текущей постройки) × min(1, потеря_в_ходах / срок)`, где `DoF` был
    **счётом** переходов меню (> 1), поэтому `ln` был положителен. В `v0.11` DoF
    сущности лежит в `[0, 1]`, и `ln(DoF) ≤ 0`: та же формула дала бы **отрицательную**
    цену, то есть премию за отказ. Поэтому переносится ИЗМЕРЕННАЯ величина — потерянные
    ЩИТЫ, — а не вывод прежнего измерителя: щиты уже оплачены и потеряны, и это факт
    мира, не зависящий от валюты индекса. Превращение щитов в цену опции — отдельный
    шаг и объявляется отдельно (в v0.9.1 он был частью другой валюты).

    Доля срока возвращается рядом: если потерянная работа не меньше срока текущей
    постройки, она не состоится никогда — это и есть потолок `min(1, …)`.
    Величина не выдумывается: нечего считать — `None` **с причиной**, а не молча.
    """
    if same_variant:
        return 0.0, 0.0, "вариант тот же — терять нечего"
    loss = lost_shields if lost_shields is not None else loss_median
    if loss is None:
        return None, 0.0, "потеря щитов при смене не измерена — считать нечем"
    source = "замер" if lost_shields is not None else "ссылка v2 (медиана 3, 80 наблюдений)"
    if not net_shield_gain or float(net_shield_gain) <= 0.0 or not current_eta:
        return float(loss), 0.0, (f"потеря {float(loss):g} щитов ({source}); чистый прирост "
                                  f"щитов или срок постройки неизвестны — доля не считается")
    lost_turns = float(loss) / float(net_shield_gain)
    share = min(1.0, lost_turns / float(current_eta))
    return float(loss), float(share), (f"потеря {float(loss):g} щитов ({source}) = "
                                       f"{lost_turns:.2f} хода работы; доля срока {share:.3f}")
