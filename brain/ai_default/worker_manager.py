"""Его управляющий городом: выбор расстановки жителей (`server/cityturn.c:308-358`).

Перенесено буквально из `set_default_city_manager` и `auto_arrange_workers`:

* веса выходов (`cmp->factor`): размер 1 — еда 20, щиты 5, торговля 0, золото 2, наука 2,
  роскошь 0, «счастье» 0; размер 2 и выше до `notradesize` — еда 15, выше — 10; при ПОЛНОЙ
  житнице еда 0 («больше пищи не нужно»);
* наименьшие избытки (`cmp->minimal_surplus`): еда 1 (0 при полной житнице), щиты 1,
  торговля 0, золото −∞, роскошь 0, наука 0;
* комментарий его кода: «Growing to size 2 is the highest priority» — отсюда еда 20.

Разница весов и даёт его поведение: пока город мал, он готов потерять щиты ради еды, потому что
следующий житель важнее; когда житница полна, еда перестаёт что-либо весить и вес переходит щитам.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

FACTOR_FOOD_SIZE1 = 20.0
FACTOR_FOOD_BELOW_TRADE = 15.0
FACTOR_FOOD_ABOVE_TRADE = 10.0
FACTOR_FOOD_FULL_GRANARY = 0.0
FACTOR_SHIELD = 5.0
FACTOR_TRADE = 0.0          # торговля сама по себе ничего не стоит: только золото и наука
FACTOR_GOLD = 2.0
FACTOR_LUXURY = 0.0
FACTOR_SCIENCE = 2.0
FACTOR_HAPPY = 0.0

MIN_SURPLUS_FOOD = 1.0
MIN_SURPLUS_FOOD_FULL_GRANARY = 0.0
MIN_SURPLUS_SHIELD = 1.0
MIN_SURPLUS_TRADE = 0.0
MIN_SURPLUS_LUXURY = 0.0
MIN_SURPLUS_SCIENCE = 0.0


def factors(size: float, *, granary_full: bool = False,
            notradesize: int = 0) -> dict[str, float]:
    """Веса выходов города — как у него, по размеру города и состоянию житницы.

    Ветвление ровно как в источнике (`server/cityturn.c:320-338`): нулевой вес еды при полной
    житнице ставится ТОЛЬКО в ветви `csize > 1`; для размера 1 он не ставится никогда, потому что и
    условия у него стоят по-разному. На практике это недостижимо (житница размера 1 полной не бывает),
    но приведено к источнику буквально, чтобы расхождений не осталось ни одного.
    """
    size = float(size or 0.0)
    if size <= 1.0:
        food = FACTOR_FOOD_SIZE1
    else:
        if int(size) <= int(notradesize or 0):
            food = FACTOR_FOOD_BELOW_TRADE
        else:
            food = FACTOR_FOOD_ABOVE_TRADE
        if granary_full:
            food = FACTOR_FOOD_FULL_GRANARY
    return {"food": food, "shield": FACTOR_SHIELD, "trade": FACTOR_TRADE,
            "gold": FACTOR_GOLD, "luxury": FACTOR_LUXURY, "science": FACTOR_SCIENCE,
            "happy": FACTOR_HAPPY}


def minimal_surplus(*, granary_full: bool = False) -> dict[str, float]:
    """Наименьшие избытки города — как у него."""
    return {"food": (MIN_SURPLUS_FOOD_FULL_GRANARY if granary_full else MIN_SURPLUS_FOOD),
            "shield": MIN_SURPLUS_SHIELD, "trade": MIN_SURPLUS_TRADE,
            "luxury": MIN_SURPLUS_LUXURY, "science": MIN_SURPLUS_SCIENCE}


def tile_value(food: float, shield: float, trade: float, weights: Mapping[str, float]) -> float:
    """Ценность клетки по его весам: еда и щиты прямо, торговля через золото и науку.

    У него `factor[O_TRADE] = 0`, а `factor[O_GOLD] = factor[O_SCIENCE] = 2`: торговля даёт
    золото и науку по правилам мира, поэтому её вклад считается как `trade × (gold + science)`.
    """
    w = weights
    return (float(food) * float(w.get("food", 0.0))
            + float(shield) * float(w.get("shield", 0.0))
            + float(trade) * (float(w.get("gold", 0.0)) + float(w.get("science", 0.0))))


def best_arrangement(
    yields_by_offset: Mapping[tuple[int, int], tuple[float, float, float]],
    *,
    size: float,
    candidates: Iterable[tuple[int, int]] = (),
    food_cost: float = 2.0,
    granary_full: bool = False,
    notradesize: int = 0,
) -> dict[str, Any]:
    """ЛУЧШАЯ расстановка — полный поиск с отсечением, как у него в CMA (`cm.c`).

    Зачем отдельная функция. Наш `choose_arrangement` берёт лучшие клетки жадно и чинит нехватку
    еды заменой: он не доказывает, что найденная комбинация лучшая. У него поиск полный — отсекаются
    только заведомо худшие ветви (`choice_is_promising`, `cm.c:1655`), а оценка ветви сверху — по
    каждому выходу отдельно (`compute_max_stats_heuristic`, `cm.c:1584`). Здесь перенесено ровно это:
    отсечение не меняет ответ, поэтому найденная расстановка максимальна по его весам.

    Возвращает `{"chosen": [...], "surplus": {...}, "value": float}`. Если требования наименьших
    избытков не выполнимы ни при каком наборе, возвращается лучший найденный набор с `feasible=False`
    — молчание не выдаётся за успех.
    """
    size = float(size or 1.0)
    slots = max(1, int(round(size)) + 1)          # центр + `размер` жителей
    weights = factors(size, granary_full=granary_full, notradesize=notradesize)
    mins = minimal_surplus(granary_full=granary_full)

    def yields(off: tuple[int, int]) -> tuple[float, float, float]:
        if off == (0, 0):
            return yields_by_offset.get((0, 0), (1.0, 1.0, 0.0))
        return yields_by_offset.get(off, (0.0, 0.0, 0.0))

    pool: list[tuple[int, int]] = []
    for off in candidates:
        if off == (0, 0) or off in pool:
            continue
        pool.append(off)
    # Порядок обхода — по ценности: с ним отсечение работает раньше (у него тот же смысл обхода).
    pool.sort(key=lambda o: -tile_value(*yields(o), weights))

    center = (0, 0)
    need_cost = float(food_cost) * size
    min_food = float(mins["food"])
    min_shield = float(mins["shield"])

    best: dict[str, Any] = {"chosen": [], "value": float("-inf"), "feasible": False}

    def value_of(offs: Iterable[tuple[int, int]]) -> float:
        return sum(tile_value(*yields(o), weights) for o in offs)

    def bound(prefix_value: float, remaining: int, start: int) -> float:
        """Потолок ветви: текущее плюс лучшие `remaining` клеток, ещё доступные после `start`."""
        if remaining <= 0:
            return prefix_value
        rest = sorted((tile_value(*yields(o), weights) for o in pool[start:]), reverse=True)
        return prefix_value + sum(rest[:remaining])

    def dfs(i: int, taken: list[tuple[int, int]], remaining: int,
            food: float, shield: float) -> None:
        nonlocal best
        if remaining == 0:
            feas = (food - need_cost >= min_food - 1e-9) and (shield >= min_shield - 1e-9)
            if not feas:
                # Его поведение при отсутствии годной расстановки (`cmr->found_a_valid = FALSE`):
                # НЕ выдумывать замену, а сказать «годной нет» — вызывающий оставляет как было.
                return
            cur = value_of([center] + list(taken))
            if cur > best["value"]:
                best = {"chosen": [center] + list(taken), "value": cur, "feasible": True,
                        "surplus": {"food": food - need_cost, "shield": shield}}
            return
        if i >= len(pool):
            return
        # Отсечение 1: даже при самом щедром допущении не хватает еды или щитов — ветвь бесполезна.
        max_food = max((yields(o)[0] for o in pool[i:]), default=0.0)
        max_shield = max((yields(o)[1] for o in pool[i:]), default=0.0)
        if food + max_food * remaining - need_cost < min_food - 1e-9:
            return
        if shield + max_shield * remaining < min_shield - 1e-9:
            return
        # Отсечение 2: потолок ветви не превосходит уже найденное — ответ из неё не изменится.
        if best["feasible"] and bound(value_of([center] + list(taken)), remaining,
                                      i) <= float(best["value"]) + 1e-9:
            return
        y = yields(pool[i])
        dfs(i + 1, taken + [pool[i]], remaining - 1, food + y[0], shield + y[1])
        dfs(i + 1, taken, remaining, food, shield)

    c = yields(center)
    # Жителей столько, сколько есть клеток: если клеток меньше, город занимает столько,
    # сколько доступно (иначе поиск объявил бы «годной нет» там, где она есть).
    k = max(0, min(slots - 1, len(pool)))
    dfs(0, [], k, c[0], c[1])
    return best


def choose_arrangement(
    yields_by_offset: Mapping[tuple[int, int], tuple[float, float, float]],
    *,
    size: float,
    worked: Iterable[tuple[int, int]] = (),
    free: Iterable[tuple[int, int]] = (),
    food_cost: float = 2.0,
    granary_full: bool = False,
    notradesize: int = 0,
) -> dict[str, Any]:
    """Желаемая расстановка жителей — его задачей целиком, а не по одной клетке.

    Клеток город обрабатывает `размер + 1` (центр бесплатен и обрабатывается всегда). Берём
    лучшие по его ценности, но проверяем наименьшие избытки: если выбранное даёт меньше
    `minimal_surplus[food]`, меняем самую дешёвую выбранную клетку на лучшую по еде среди
    свободных — и так до выполнения условия. Возвращаем желаемый набор смещений и посчитанный
    избыток: он же служит доказательством, что обмен «снять → занять» не приведёт к голоду.
    """
    size = float(size or 1.0)
    cells_wanted = max(1, int(round(size)) + 1)
    weights = factors(size, granary_full=granary_full, notradesize=notradesize)
    mins = minimal_surplus(granary_full=granary_full)

    candidates: list[tuple[int, int]] = [(0, 0)]
    for off in list(worked) + [f for f in free if f != (0, 0)]:
        if off not in candidates:
            candidates.append(off)

    def yields(off: tuple[int, int]) -> tuple[float, float, float]:
        if off == (0, 0):
            # Центр города по правилам мира даёт минимум 1/1/0 (бесплатный центр).
            return yields_by_offset.get((0, 0), (1.0, 1.0, 0.0))
        return yields_by_offset.get(off, (0.0, 0.0, 0.0))

    def total(chosen: list[tuple[int, int]]) -> tuple[float, float, float]:
        f = sum(yields(o)[0] for o in chosen)
        s = sum(yields(o)[1] for o in chosen)
        t = sum(yields(o)[2] for o in chosen)
        return f, s, t

    def surplus(chosen: list[tuple[int, int]]) -> dict[str, float]:
        f, s, t = total(chosen)
        return {"food": f - float(food_cost) * size, "shield": s, "trade": t}

    def ok(sup: Mapping[str, float]) -> bool:
        return (sup["food"] >= mins["food"] - 1e-9 and sup["shield"] >= mins["shield"] - 1e-9)

    # Центр обрабатывается всегда и бесплатно (его `city_center`), поэтому он входит в набор
    # безусловно, а остальные клетки добираются по ценности до «размер + 1».
    others = [o for o in candidates if o != (0, 0)]
    chosen = [(0, 0)] + sorted(
        others, key=lambda o: -tile_value(*yields(o), weights))[:max(0, cells_wanted - 1)]
    guards = 0
    while not ok(surplus(chosen)) and guards < 40:
        guards += 1
        # меняем самую дешёвую выбранную НЕ-центр клетку на лучшую по еде среди прочих
        replaceable = [o for o in chosen if o != (0, 0)]
        if not replaceable:
            break
        worst = min(replaceable, key=lambda o: tile_value(*yields(o), weights))
        rest = [o for o in candidates if o not in chosen]
        if not rest:
            break
        better_food = max(rest, key=lambda o: (yields(o)[0], tile_value(*yields(o), weights)))
        if yields(better_food)[0] <= yields(worst)[0]:
            break
        chosen = [o for o in chosen if o != worst] + [better_food]
    sup = surplus(chosen)
    _f, _s, _t = total(chosen)
    return {"chosen": sorted(set(chosen)), "food": _f, "shield": _s, "trade": _t,
            "surplus": sup, "ok": ok(sup), "weights": weights, "minimal": mins}
