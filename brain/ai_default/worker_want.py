"""ЕГО ЦЕННОСТЬ РАБОТЫ НА ЗЕМЛЕ — перенос ядра `settler_evaluate_improvements`.

Зачем. В `dai_auto_settler_run` (`ai/default/daisettler.c:1121-1134`) поселенец выбирает так:

    МИР = find_best_city_placement(...)          → `result->result`   (ценность площадки)
    ЗЕМЛЯ = settler_evaluate_improvements(...)   → `best_impr`        (ценность работы)
    if (result && result->result > best_impr)  → AUT_BUILD_CITY  (идёт основывать)
    else if (best_impr > 0)                    → AUT_AUTO_SETTLER (работает на земле)
    else                                       → работы нет

Числа работы считает `settler_evaluate_improvements` (`server/advisors/autoworkers.c:439`), и его
ядро — последние строки функции (`:795-801`):

    best_newv = amortize((best_newv - best_oldv + best_extra) * WORKER_FACTOR, best_delay);
    best_newv /= WORKER_FACTOR;
    best_newv = MAX(best_newv, 0);

где `oldv = city_tile_value(pcity, ptile, 0, 0)` — ценность клетки ДЛЯ ГОРОДА сейчас, `newv` — она же
после работы, `best_delay` — сколько ходов идёт работа, `WORKER_FACTOR = 1024` (`:70`) — фиксированная
точка (в целочисленной арифметике C делить на неё нужно, чтобы не потерять дробную часть).

Здесь перенесено РОВНО это ядро. Чего нет и почему это сказано прямо: у него `newv` берётся обходом
ВСЕГО радиуса города с маршрутизатором (`city_tile_iterate` + `pf_map`), и оценку клетки для города
делает `city_tile_value` из `cm.c`; у нас ценность клетки — наш же `tile_sum` с приоритетами
встроенного ИИ, а работы берутся только те, что мир предлагает поселенцу СЕЙЧАС (он стоит на клетке).
Это подмножество его поиска, а не другая арифметика.
"""

from __future__ import annotations

from brain.ai_default.values import amortize

#: ЕГО `WORKER_FACTOR` (`autoworkers.c:70`).
WORKER_FACTOR: int = 1024

#: Приоритеты встроенного ИИ для ценности клетки. У него они приходят из `ai_common`
#: (`AI_FOOD_WEIGHTING`, `AI_SCIENCE_PRIORITY`, `AI_SHIELD_WEIGHTING`); у нас те же значения
#: заданы запасными в `env/site_eval.py` — здесь они повторены ровно теми же числами.
FOOD_PRIORITY_FALLBACK: float = 30.0
SCIENCE_PRIORITY_FALLBACK: float = 21.6
SHIELD_PRIORITY_FALLBACK: float = 17.0


def improvement_want(value_before: float, value_after: float, delay: int) -> float:
    """ЕГО ядро (`autoworkers.c:795-801`): `amortize(Δ * WORKER_FACTOR, delay) / WORKER_FACTOR`.

    `value_before`/`value_after` — ценность клетки для города до и после работы (у него `oldv` и
    `newv`), `delay` — сколько ходов идёт работа (у него `best_delay`). Отрицательное Δ даёт 0
    (`MAX(best_newv, 0)`): работа, ухудшающая клетку, ценности не имеет.
    """
    raw = (float(value_after) - float(value_before)) * WORKER_FACTOR
    return max(0.0, amortize(raw, int(delay)) / WORKER_FACTOR)


def tile_value(food: float, shield: float, trade: float, *,
               food_priority: float = FOOD_PRIORITY_FALLBACK,
               science_priority: float = SCIENCE_PRIORITY_FALLBACK,
               shield_priority: float = SHIELD_PRIORITY_FALLBACK) -> float:
    """Ценность клетки для города — та же сумма, что и в оценке площадки (`tile_sum`).

    Порядок слагаемых — его: еда, торговля, щиты.
    """
    return (float(food) * float(food_priority)
            + float(trade) * float(science_priority)
            + float(shield) * float(shield_priority))


def best_improvement_want(entries: list[tuple[float, float, int]]) -> float:
    """Лучшая работа из списка: `[(ценность_до, ценность_после, ходов)]` → его `best_newv`.

    Пустой список — работы нет, ценность 0 (его `best_newv = 0` в начале поиска).
    """
    best = 0.0
    for before, after, delay in entries:
        want = improvement_want(before, after, delay)
        if want > best:
            best = want
    return best
