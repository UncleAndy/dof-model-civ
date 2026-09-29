"""Правила назначения жителей: гипотезы о том, как игра выбирает клетки.

Зачем это нужно. Модель площадки предсказывает выход города как «лучшие `size+1`
клеток **по каждому каналу отдельно**»: для еды — самые сытные, для щитов —
самые производительные, для торговли — самые торговые. Проверка на живых
городах показала, что по еде это верно (прогноз ни разу не ниже факта), а по
щитам и торговле свойство нарушается — то есть модель берёт **не тот набор
клеток**, который обрабатывает игра.

Гипотеза, которую надо различить: игра назначает жителей **одним** набором
клеток (например, «сначала еда, потом щиты»), и уже из этого набора берутся все
три канала. Тогда щиты и торговля завышаются ровно потому, что модель дала
каждому каналу свой набор — лучший именно для него.

Здесь наборы-кандидаты описаны явно, чтобы вопрос решался сравнением по уже
собранным данным, а не спором. Правило, которое воспроизведёт наблюдение,
и есть правило игры.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from .site_eval import CITY_CENTRE_MIN

#: Клетка — [еда, щиты, торговля]. Центр всегда первый и всегда обрабатывается.
Tile = Sequence[float]


def _centre(t: Tile, centre_min: float) -> tuple[float, float, float]:
    """Центр города: не меньше `centre_min` по каждому каналу.

    Нулевую клетку центра НЕ трогаем — ноль там может значить «не знаем»
    (нераскрытая клетка), и это не повод получить единицу.
    """
    if centre_min <= 0 or (t[0] == 0 and t[1] == 0 and t[2] == 0):
        return (float(t[0]), float(t[1]), float(t[2]))
    return (max(float(t[0]), centre_min), max(float(t[1]), centre_min),
            max(float(t[2]), centre_min))


def _key_food(t: Tile) -> tuple[float, float]:
    return (t[0], t[1])


def _key_shield(t: Tile) -> tuple[float, float]:
    return (t[1], t[0])


def _key_trade(t: Tile) -> tuple[float, float]:
    return (t[2], t[0])


def _key_total(t: Tile) -> tuple[float, float]:
    return (t[0] + t[1] + t[2], t[0])


def _key_food_then_shield(t: Tile) -> tuple[float, float, float]:
    # Губернатор Freeciv по умолчанию кормит город первым делом, а при равной
    # еде берёт больше щитов.
    return (t[0], t[1], t[2])


#: Правила «одним набором»: центр + k лучших по ключу, затем все три канала
#: считаются по ЭТОМУ набору.
SINGLE_SET_RULES: dict[str, Callable[[Tile], tuple]] = {
    'single_food': _key_food,
    'single_shield': _key_shield,
    'single_trade': _key_trade,
    'single_total': _key_total,
    'single_food_then_shield': _key_food_then_shield,
}

#: Правило «каждому каналу свой набор» — как сейчас делает модель площадки.
PER_CHANNEL_RULE = 'per_channel'


def indices_for(tiles: Sequence[Tile], size: int,
                key: Callable[[Tile], tuple]) -> list[int]:
    """Индексы обрабатываемых клеток: центр (0) плюс `size` лучших по ключу."""
    k = max(0, int(size))
    rest = sorted(range(1, len(tiles)), key=lambda i: key(tiles[i]), reverse=True)
    return [0] + rest[:k]


def predict(tiles: Sequence[Tile], size: int, rule: str,
            centre_min: float = CITY_CENTRE_MIN) -> tuple[float, float, float]:
    """Прогноз (еда, щиты, торговля) по правилу.

    * `per_channel` — лучший набор для каждого канала отдельно (текущая модель);
    * `single_*`  — один набор клеток, все каналы считаются по нему.

    `centre_min` — минимум городского центра по каждому каналу (измерено, см.
    `site_eval.CITY_CENTRE_MIN`). Без него сравнение с фактом заведомо
    проигрышно: центр на карте часто нулевой по торговле, а город получает 1.
    """
    if not tiles:
        return (0.0, 0.0, 0.0)
    tiles = [_centre(tiles[0], centre_min)] + list(tiles[1:])
    if rule == PER_CHANNEL_RULE:
        return tuple(  # type: ignore[return-value]
            sum(tiles[i][ch] for i in indices_for(
                tiles, size, (lambda t, ch=ch: (t[ch], t[0]))))
            for ch in range(3))
    key = SINGLE_SET_RULES[rule]
    chosen = indices_for(tiles, size, key)
    return tuple(  # type: ignore[return-value]
        sum(tiles[i][ch] for i in chosen) for ch in range(3))


def all_rules() -> list[str]:
    return [PER_CHANNEL_RULE] + sorted(SINGLE_SET_RULES)


# ── Порог вердикта: задан ДО данных ─────────────────────────────────────────
#
# Соблазн объявить правило «найденным» по максимуму из таблицы велик, и он уже
# приводил к ложному выводу: на 8 строках скрипт выбрал лучшее из шести правил
# (4 точных совпадения из 24) и заявил, что «подтверждается один набор клеток».
# Это шум, а не результат. Поэтому вердикт — счёт по заранее заданным условиям:
# мало строк — нет вердикта; правило должно работать на ВСЕХ трёх каналах и
# заметно опережать следующее, иначе оно неотличимо от случайного совпадения.
VERDICT_MIN_ROWS = 20
VERDICT_MIN_SHARE = 0.70
VERDICT_MIN_MARGIN = 0.10


def verdict(exact: dict[str, list[int]], n_rows: int) -> dict[str, Any]:
    """Вердикт по правилу: счёт, а не суждение.

    `exact` — число точных совпадений на каждый канал для каждого правила.
    """
    if n_rows < VERDICT_MIN_ROWS:
        return {'ok': False, 'rule': None,
                'reason': (f'строк {n_rows} < {VERDICT_MIN_ROWS}: вердикта нет '
                           f'(это «мало данных», а не «правило не найдено»)')}
    total = 3 * n_rows
    shares = {r: sum(c) / total for r, c in exact.items()}
    ranked = sorted(shares.items(), key=lambda kv: kv[1], reverse=True)
    best_rule, best_share = ranked[0]
    second_share = ranked[1][1] if len(ranked) > 1 else 0.0
    per_channel = [c / n_rows for c in exact[best_rule]]
    if best_share < VERDICT_MIN_SHARE:
        return {'ok': False, 'rule': None,
                'reason': (f'лучшее правило `{best_rule}` воспроизводит лишь '
                           f'{best_share:.0%} каналов-случаев (< '
                           f'{VERDICT_MIN_SHARE:.0%}): ни одно правило не '
                           f'подтверждено')}
    if min(per_channel) < VERDICT_MIN_SHARE:
        weak = CHANNEL_NAMES[per_channel.index(min(per_channel))]
        return {'ok': False, 'rule': None,
                'reason': (f'`{best_rule}` работает по каналу «{weak}» лишь в '
                           f'{min(per_channel):.0%} случаев: правило не может '
                           f'быть правилом игры, если не сходится на канале')}
    if best_share - second_share < VERDICT_MIN_MARGIN:
        return {'ok': False, 'rule': None,
                'reason': (f'`{best_rule}` ({best_share:.0%}) отрывается от '
                           f'следующего лишь на {best_share - second_share:.0%} '
                           f'(< {VERDICT_MIN_MARGIN:.0%}): правила неразличимы')}
    return {'ok': True, 'rule': best_rule, 'share': best_share,
            'reason': (f'`{best_rule}` воспроизводит {best_share:.0%} каналов-'
                       f'случаев, отрыв {best_share - second_share:.0%}, '
                       f'по каждому каналу не ниже {min(per_channel):.0%}')}


CHANNEL_NAMES = ("еда", "щиты", "торговля")
