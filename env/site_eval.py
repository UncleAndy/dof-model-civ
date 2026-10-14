"""Оценка площадки города и контрфактический рост (фактор (б)).

Всё здесь выведено из данных мира, подтверждённых на живом стенде
(`scripts/inspect_terrain_legend.py`, `scripts/inspect_terrain_live.py`):

* `map['output'][x][y]` — итоговый выход клетки (террейн + ресурс + улучшения
  уже сложены сервером), каналы 0/1/2 = еда / щиты / торговля;
* нераскрытая клетка даёт нулевой выход — это **отсутствие знания**, а не
  «нулевые опции» (Axiom 5/7), поэтому неизвестные клетки не считаются нулём,
  а заполняются средним по видимым с полосой неопределённости;
* область влияния города — 21 клетка (квадрат 5×5 без угловых,
  `city_radius_sq = 5`), центральная клетка работает бесплатно, поэтому
  обрабатывается `size + 1` клеток;
* амбар = `10 × (size + 1)` еды (правило стенда: `granary = 10*(size+1)`);
* житель съедает `food_cost = 2` (подтверждено `rules.food_cost`).

Модуль не хранит константы сам: коэффициенты берутся из снимка модели
(`WorldModel.values()`), чтобы формулы читали модель, а не литералы.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .terrain_work import tile_terrain_extras


def _ai_values():
    """Модуль чисел встроенного ИИ (§13.187) — импорт по месту, чтобы `env` не тянул
    `brain` на этапе загрузки пакета (иначе цикл импортов и запросы тестов падают)."""
    from brain.ai_default import values as _ai
    return _ai

#: Область влияния города: квадрат 5×5 без угловых == 21 клетка.
CITY_RADIUS_SQ: int = 5

#: Амбар: стоимость роста из размера s составляет GRANARY_PER_SIZE × (s + 1).
GRANARY_PER_SIZE: float = 10.0

#: Смещения рабочих клеток БЕЗ центра: евклидов квадрат ≤ 5, углы исключены.
#: Вместе с центром это даёт 21 клетку области влияния (квадрат 5×5 без углов).
WORKABLE_OFFSETS: tuple[tuple[int, int], ...] = tuple(
    (dx, dy)
    for dx in range(-2, 3)
    for dy in range(-2, 3)
    if (dx or dy) and dx * dx + dy * dy <= CITY_RADIUS_SQ
)


@dataclass
class SiteEvaluation:
    """Оценка площадки по клеткам вокруг точки."""

    x: int
    y: int
    size: int
    food: float = 0.0            # лучшие (size+1) клеток, включая бесплатный центр
    shields: float = 0.0
    trade: float = 0.0
    food_low: float = 0.0        # нижняя граница (неизвестные клетки = 0)
    food_high: float = 0.0       # верхняя граница (неизвестные = лучший видимый)
    known_tiles: int = 0
    total_tiles: int = 0
    unknown_ratio: float = 0.0
    food_surplus: float = 0.0    # food − food_cost × size
    gate_size: int = 1           # размер, на котором проверяется гейт качества
    gate_food: float = 0.0       # еда лучших (gate_size+1) клеток — то, что гейт видит
    #: ОПТИМИСТИЧНАЯ граница той же величины: неизвестные клетки в ней берутся как
    #: лучшая видимая (Axiom 5/7). Именно она решает годность площадки, поэтому она
    #: хранится рядом с `gate_food`, а не живёт локальной переменной: без неё
    #: «почему площадка не годна» не проверить замером.
    gate_food_high: float = 0.0
    coastal: bool = False        # есть ли выход к воде в области города
    resource_types: tuple[str, ...] = ()   # различные ИЗМЕРЕННЫЕ ресурсы в области
    option_bonus: float = 0.0    # опции площадки: берег + ресурсы, с потолком
    #: ── Оценка ВСТРОЕННОГО ИИ-игрока (§13.188) — его числа, не наши ──
    #: `ai_center_sum`/`ai_best_sum`/`ai_remaining` — из `cityresult_fill`
    #: (daisettler.c): сумма клетки по весам ИИ (еда 30, торговля весом науки 21.6,
    #: щиты 17, поправки ×1.5 и ×2 за еду ≥ 2), лучшая рабочая клетка и «потенциал»
    #: остальных (делённых на GROWTH_POTENTIAL_DEEMPHASIS 8).
    ai_center_sum: float = 0.0
    ai_best_sum: float = 0.0
    ai_remaining: float = 0.0
    ai_want: float = 0.0         # его `result->total` для нового города на этой площадке
    starved_food: bool = False   # его `food_starvation`
    starved_shield: bool = False  # его `shield_starvation`
    #: ── Диагностика §13.320: та же площадка, но из ОДНОЙ совместной расстановки ──
    #: Ресурсы выше набраны НЕЗАВИСИМО (еда по лучшим по еде, щиты по лучшим по щитам),
    #: поэтому одни клетки считаются дважды. Здесь — честное «что город реально может».
    joint_food: float = 0.0
    joint_shields: float = 0.0
    joint_trade: float = 0.0
    joint_fed: bool = False
    #: Насколько независимый набор завысил щиты относительно совместного (диагностика).
    shields_inflated: float = 0.0
    viable: bool = False         # прошла ли гейт минимального качества
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "x": self.x, "y": self.y, "size": self.size,
            "food": round(self.food, 3), "shields": round(self.shields, 3),
            "trade": round(self.trade, 3),
            "food_low": round(self.food_low, 3), "food_high": round(self.food_high, 3),
            "known_tiles": self.known_tiles, "total_tiles": self.total_tiles,
            "unknown_ratio": round(self.unknown_ratio, 3),
            "food_surplus": round(self.food_surplus, 3),
            "gate_size": self.gate_size, "gate_food": round(self.gate_food, 3),
            "gate_food_high": round(self.gate_food_high, 3),
            "coastal": self.coastal, "resource_types": list(self.resource_types),
            "option_bonus": round(self.option_bonus, 3),
            "joint_food": round(self.joint_food, 3),
            "joint_shields": round(self.joint_shields, 3),
            "joint_trade": round(self.joint_trade, 3),
            "joint_fed": self.joint_fed,
            "shields_inflated": round(self.shields_inflated, 3),
            "viable": self.viable, "reason": self.reason,
        }


def _as_array(layer: Any):
    """Слой наблюдения -> индексируемая структура, либо None."""
    if layer is None:
        return None
    try:
        import numpy as np

        return np.asarray(layer)
    except Exception:  # pragma: no cover - numpy отсутствует
        return layer


def in_bounds(map_obs: dict[str, Any], x: int, y: int) -> bool:
    """Есть ли такая клетка на карте.

    Карта — **цилиндр**: по X края соединены (`x` замыкается), по Y — нет: над
    верхним рядом и под нижним клеток не существует (полюса, `TF_WRAPX = 1`,
    `TF_WRAPY = 0` — проверено у стенда). Раньше `tile_output` замыкал обе оси, и
    площадка у полюса получала соседей с противоположного края карты — выход и
    годность считались по клеткам, которых рядом нет (измерено: карта 78 × 52).

    Отличать «за краем» от «не раскрыто» обязательно: неизвестные клетки внутри
    площадки заполняются средним видимым (Axiom 5/7), и если бы закрайние попадали
    в тот же мешок, площадка у полюса снова получила бы чужие числа.
    """
    layer = _as_array((map_obs or {}).get("output"))
    if layer is None:
        return False
    ya = layer.shape[1]
    return 0 <= y < ya


def tile_output(map_obs: dict[str, Any], x: int, y: int) -> tuple[float, float, float, bool]:
    """Выход клетки (food, shields, trade) и признак «клетка раскрыта».

    Раскрытость определяется по ненулевому выходу: нераскрытые клетки в
    наблюдении дают ровно (0, 0, 0), а слой террейна при этом заполнен, так что
    террейн как признак знания не годится.

    По X координата замыкается (цилиндр), по Y — нет: за краем карты клетки нет и
    возвращаются нули. Отличить «за краем» от «не раскрыто» можно через
    `in_bounds`; в самой модели площадки закрайние клетки ВЫБРАСЫВАЮТСЯ из набора
    рабочих, а не заполняются средним.
    """
    layer = _as_array((map_obs or {}).get("output"))
    if layer is None:
        return 0.0, 0.0, 0.0, False
    xa, ya = layer.shape[0], layer.shape[1]
    if not 0 <= y < ya:
        return 0.0, 0.0, 0.0, False     # за краем: клетки нет (не «не раскрыто»)
    x %= xa                              # X: карта — цилиндр
    cell = layer[x][y]
    try:
        vals = [float(v) for v in cell][:3]
    except TypeError:
        vals = [float(cell), 0.0, 0.0]
    food, shields, trade = (vals + [0.0, 0.0, 0.0])[:3]
    return food, shields, trade, (food, shields, trade) != (0.0, 0.0, 0.0)


#: Минимум городского центра по каждому каналу.
#:
#: ИЗМЕРЕНО на живых городах 2026-09-26. Карта отдаёт выход *клетки*, а город
#: на ней получает не меньше единицы по каждому каналу: в 7 из 8 полностью
#: разведанных площадок наблюдённый выход города (еда/щиты/торговля) НЕ
#: раскладывался ни на один набор клеток вообще, и торговля равнялась 1 там, где
#: у всех 21 клетки торговля 0. С поправкой «центр = max(клетка, 1)» набор
#: находится у 6 из 8 строк против 1 из 8 без неё. Вариант «+1» дал 4 из 8,
#: «+1 только к еде» — 1 из 8, то есть это именно МИНИМУМ, а не бонус.
CITY_CENTRE_MIN = 1.0


def city_centre_output(map_obs: dict[str, Any], x: int, y: int
                       ) -> tuple[float, float, float, bool]:
    """Выход центральной клетки города: клетка карты, но не меньше `CITY_CENTRE_MIN`.

    Нераскрытую клетку поправка не трогает: (0,0,0) там означает «не знаем», и
    превращать незнание в единицу — это подгонка (Axiom 5/7).
    """
    food, shields, trade, known = tile_output(map_obs, x, y)
    if not known:
        return food, shields, trade, known
    return (max(food, CITY_CENTRE_MIN), max(shields, CITY_CENTRE_MIN),
            max(trade, CITY_CENTRE_MIN), known)


def joint_site_outputs(tiles, size, food_cost):
    """ВЫХОДЫ ПЛОЩАДКИ ИЗ ОДНОЙ СОВМЕСТНОЙ РАССТАНОВКИ (§13.320).

    Центр работает бесплатно, `size` рабочих клеток выбираются ВМЕСТЕ — город не может
    работать «лучшие по еде» и «лучшие по щитам» одновременно. Возвращает
    `(food, shields, trade, fed)` лучшей расстановки, которая кормит `size` жителей
    (среди кормящих берём наибольшие щиты); если не кормит ни одна — берём наибольшую еду
    и `fed=False`. Число сочетаний ограничено: при переборе сверх предела берём жадную
    расстановку (и это видно по `fed=False` вместе с пометкой в замечании вызывающего).
    """
    tiles = list(tiles or [])
    if not tiles:
        return (0.0, 0.0, 0.0, False)
    centre, rest = tiles[0], list(tiles[1:])
    k = min(len(rest), max(1, int(size)))
    need_food = food_cost * max(1, int(size))
    best_fed = None   # (щиты, еда, торговля)
    best_any = None   # (еда, щиты, торговля)
    import itertools, math
    n_comb = math.comb(len(rest), k) if len(rest) >= k else 0
    combos = itertools.combinations(range(len(rest)), k) if n_comb <= 150000 else None
    if combos is None:
        order = sorted(range(len(rest)), key=lambda i: (rest[i][0], rest[i][1]), reverse=True)
        combos = [tuple(order[:k])]
    for combo in combos:
        f = centre[0] + sum(rest[i][0] for i in combo)
        s = centre[1] + sum(rest[i][1] for i in combo)
        tr = centre[2] + sum(rest[i][2] for i in combo)
        if best_any is None or (f, s) > (best_any[0], best_any[1]):
            best_any = (f, s, tr)
        if f >= need_food and (best_fed is None or (s, f) > (best_fed[0], best_fed[1])):
            best_fed = (s, f, tr)
    if best_fed is not None:
        s, f, tr = best_fed
        return (float(f), float(s), float(tr), True)
    f, s, tr = best_any
    return (float(f), float(s), float(tr), False)


def evaluate_site(map_obs: dict[str, Any], x: int, y: int, *,
                  size: int = 1, vals: dict[str, Any] | None = None) -> SiteEvaluation:
    """Оценить площадку: лучшие `size + 1` клеток в радиусе, включая центр.

    Неизвестные клетки не считаются нулём: они заполняются средним по видимым
    (лучшие варианты), и дополнительно возвращается полоса `food_low`/`food_high`.
    """
    vals = vals or {}
    food_cost = float(vals.get("FOOD_COST", 2.0))
    min_food = float(vals.get("SITE_MIN_FOOD", 6.0))

    tiles: list[tuple[float, float, float, bool]] = [city_centre_output(map_obs, x, y)]
    for dx, dy in WORKABLE_OFFSETS:
        # Клетки за краем карты (полюса) в набор НЕ входят: у площадки у полюса
        # рабочих клеток меньше, а не «такие же, но чужие».
        if in_bounds(map_obs, x + dx, y + dy):
            tiles.append(tile_output(map_obs, x + dx, y + dy))

    known = [t for t in tiles if t[3]]
    unknown_n = len(tiles) - len(known)
    site = SiteEvaluation(x=x, y=y, size=size, total_tiles=len(tiles),
                          known_tiles=len(known),
                          unknown_ratio=(unknown_n / len(tiles)) if tiles else 0.0)

    # Неизвестные клетки: средний видимый выход (не ноль) — Axiom 5/7.
    if known:
        fill = tuple(sum(t[i] for t in known) / len(known) for i in range(3))
        best_fill = tuple(max(t[i] for t in known) for i in range(3))
    else:
        # НИ ОДНОЙ видимой клетки в окне. Это не «там ничего нет»: 80.9 % клеток
        # вокруг старта выглядят ровно так (измерено), и раньше они получали ноль —
        # то есть объявлялись заведомо бесплодными. Набивку берём из ИЗМЕРЕННОГО:
        # сначала средний и лучший выход по раскрытым клеткам ЭТОГО наблюдения,
        # а если не раскрыто вообще ничего — измеренная легенда террейнов.
        _fill = vals.get("UNKNOWN_FILL")
        _best = vals.get("UNKNOWN_BEST")
        fill = tuple(float(v) for v in _fill) if _fill else (
            float(vals.get("UNKNOWN_FILL_FOOD", 1.0)),
            float(vals.get("UNKNOWN_FILL_SHIELDS", 0.57)),
            float(vals.get("UNKNOWN_FILL_TRADE", 0.29)))
        best_fill = tuple(float(v) for v in _best) if _best else (
            float(vals.get("UNKNOWN_BEST_FOOD", 2.0)),
            float(vals.get("UNKNOWN_BEST_SHIELDS", 2.0)),
            float(vals.get("UNKNOWN_BEST_TRADE", 2.0)))
    effective = list(known) + [(fill[0], fill[1], fill[2], True)] * unknown_n

    need = max(1, size) + 1  # центр + size жителей
    for idx, key in ((0, "food"), (1, "shields"), (2, "trade")):
        ranked = sorted(effective, key=lambda t: (t[idx], t[0]), reverse=True)[:need]
        setattr(site, key, float(sum(t[idx] for t in ranked)))
    low = sorted(known, key=lambda t: (t[0], t[1]), reverse=True)[:need]
    high_pool = list(known) + [(best_fill[0], best_fill[1], best_fill[2], True)] * unknown_n
    high = sorted(high_pool, key=lambda t: (t[0], t[1]), reverse=True)[:need]
    site.food_low = float(sum(t[0] for t in low))
    site.food_high = float(sum(t[0] for t in high))

    site.food_surplus = site.food - food_cost * max(1, size)

    # ── §13.320: честная совместная оценка (диагностика; решения НЕ меняет) ──
    _jt = joint_site_outputs(effective, size, food_cost)
    site.joint_food, site.joint_shields, site.joint_trade, site.joint_fed = _jt
    site.shields_inflated = site.shields - site.joint_shields
    import os as _os
    if _os.environ.get("DOF_SITE_DEBUG") == "1":
        print("  [площадка] (%d,%d) размер %d: наша оценка еда %.0f щиты %.0f | "
              "СОВМЕСТНО еда %.0f щиты %.0f (кормит=%s) → щиты завышены на %.0f"
              % (x, y, size, site.food, site.shields,
                 site.joint_food, site.joint_shields, site.joint_fed,
                 site.shields_inflated), flush=True)

    # Гейт проверяется на размере `SITE_GATE_SIZE`: смысл порога —
    # «прокормить двух жителей + запас», то есть площадка должна кормить не
    # только одного основателя. Оптимистичная граница (неизвестные клетки = лучший
    # видимый) — чтобы не запрещать город на неразведанной земле (Axiom 5/7).
    site.gate_size = max(1, int(vals.get("SITE_GATE_SIZE", 2)))
    gate_need = site.gate_size + 1
    gate_ranked = sorted(effective, key=lambda t: (t[0], t[1]), reverse=True)[:gate_need]
    gate_ranked_high = sorted(high_pool, key=lambda t: (t[0], t[1]), reverse=True)[:gate_need]
    site.gate_food = float(sum(t[0] for t in gate_ranked))
    gate_food_high = float(sum(t[0] for t in gate_ranked_high))
    site.gate_food_high = gate_food_high

    # ── Годность площадки решает ВСТРОЕННЫЙ ИИ (§13.188) ──────────────────────
    # Его правило (`daisettler.c`): площадка отвергается, если центр вместе с лучшей
    # рабочей клеткой не даёт еды больше FOOD_COST (`food_starvation`) или не даёт ни
    # одного щита (`shield_starvation`). Это ЕГО порог из его кода, а не наш затухающий
    # порог §13.166: по указанию владельца «наш ИИ строится на данных встроенного ИИ»
    # правило §13.166 здесь уступает место его правилу. Прежние `gate_food*` остаются
    # как диагностика — по ним видно, что видел бы старый порог.
    _ai = _ai_values()
    _ai_food_p = float(vals.get("AI_FOOD_WEIGHTING", 30.0))
    _ai_sci_p = float(vals.get("AI_SCIENCE_PRIORITY", 21.6))
    _ai_shield_p = float(vals.get("AI_SHIELD_WEIGHTING", 17.0))

    def _ai_tile(out: tuple[float, float, float, bool], *, center: bool = False) -> Any:
        return _ai.tile_sum(out[0], out[1], out[2],
                            food_priority=_ai_food_p, science_priority=_ai_sci_p,
                            shield_priority=_ai_shield_p, is_city_center=center)

    def _optimistic(out: tuple[float, float, float, bool]) -> tuple[float, float, float, bool]:
        """Клетка для порога встроенного ИИ: неразведанная — по лучшему видимому.

        У встроенного ИИ тумана нет: он судит по настоящему выходу клетки. У нас туман
        есть, и если подставить в ЕГО порог нули неразведанных, он объявит мёртвой любую
        площадку на неисследованной земле. Это нарушило бы правило владельца: незнание
        не есть отсутствие возможностей (Axiom 5/7). Поэтому в порог идёт лучший видимый
        выход, а сама оценка площадки (`ai_want`) считается по видимому без подстановки.
        """
        if out[3]:
            return out
        return (best_fill[0], best_fill[1], best_fill[2], True)

    ai_center = _ai_tile(_optimistic(tiles[0]), center=True)
    ai_workable = sorted((_ai_tile(_optimistic(t)) for t in tiles[1:]),
                         key=lambda t: t.sum, reverse=True)
    ai_best = ai_workable[0] if ai_workable else None
    ai_others = ai_workable[1:]
    # Оценка площадки — по ВИДИМОМУ (его `result->total` на реальных клетках),
    # а порог голода — по ЛУЧШЕМУ ВИДИМОМУ на неразведанных (см. `_optimistic`).
    ai_center_known = _ai_tile(tiles[0], center=True)
    known_workable = sorted((_ai_tile(t) for t in tiles[1:]), key=lambda t: t.sum, reverse=True)
    site.ai_center_sum = ai_center_known.sum
    site.ai_best_sum = known_workable[0].sum if known_workable else 0.0
    site.ai_remaining = sum(t.sum for t in known_workable[1:]) / _ai.GROWTH_POTENTIAL_DEEMPHASIS
    site.ai_want = _ai.site_total(ai_center_known,
                                  known_workable[0] if known_workable else None,
                                  known_workable[1:])
    site.starved_food = _ai.food_starvation(ai_center, ai_best, food_cost)
    site.starved_shield = _ai.shield_starvation(ai_center, ai_best)
    if site.starved_food:
        site.viable = False
        site.reason = (f"порог встроенного ИИ: центр {ai_center.food:.1f} + лучшая "
                       f"{ai_best.food if ai_best else 0.0:.1f} еды ≤ FOOD_COST "
                       f"{food_cost:.1f}")
    elif site.starved_shield:
        site.viable = False
        site.reason = ("порог встроенного ИИ: центр и лучшая клетка не дают ни одного щита")
    else:
        site.viable = True
        site.reason = "ok (порог встроенного ИИ)"

    # Опции площадки: берег и ресурсы. Это не выход клетки, а дополнительные пути
    # развития (гавань, морские юниты, морская торговля; ресурс ускоряет рост),
    # поэтому считается в опциях и с потолком: богатая земля не должна
    # перевешивать само существование города (Axiom 1/7).
    water = set(vals.get("WATER_TERRAINS", ("Lake", "Ocean", "Deep Ocean")))
    coast_bonus = float(vals.get("SITE_COAST_BONUS", 0.10))
    resource_bonus = float(vals.get("SITE_RESOURCE_BONUS", 0.10))
    bonus_cap = float(vals.get("SITE_OPTION_BONUS_CAP", 0.30))
    table = vals.get("MEASURED_EXTRA_EFFECTS") or {}
    resource_types: set[str] = set()
    for tx, ty in [(x, y)] + [(x + dx, y + dy) for dx, dy in WORKABLE_OFFSETS
                              if in_bounds(map_obs, x + dx, y + dy)]:
        tname, tile_extras = tile_terrain_extras(map_obs, tx, ty)
        if tname in water:
            site.coastal = True
        for extra in tile_extras:
            effect = table.get(extra)
            if effect and any(float(v) != 0.0 for v in effect):
                resource_types.add(extra)   # ресурсность — по ИЗМЕРЕНИЮ
    site.resource_types = tuple(sorted(resource_types))
    site.option_bonus = min(bonus_cap,
                            (coast_bonus if site.coastal else 0.0)
                            + resource_bonus * len(site.resource_types))
    return site


def growth_box(size: int) -> float:
    """Сколько еды нужно, чтобы вырасти из размера `size` (амбар 10×(size+1))."""
    return GRANARY_PER_SIZE * (max(1, size) + 1)


def hypothetical_city_obs(site: SiteEvaluation, *, size: int = 1,
                          food_cost: float = 2.0, capital: bool = True) -> dict[str, Any]:
    """Наблюдение города, каким он был бы основан на этой площадке.

    Нужно, чтобы оценить город формулой города (`city_options`), а не отдельной
    «оценкой площадки»: тогда прогноз и факт считаются одним кодом, и модель не
    может разойтись сама с собой.

    * `surplus_food` берётся **валовым** — это семантика самого поля стенда
      (у реального города на площадке с 2 еды за ход поле показывало 2, а не 0);
    * `granary_size = 10 × (size + 1)` — правило стенда;
    * у столицы бесплатный `Palace` — он даёт первый множитель города, и именно
      поэтому основание первого города дороже последующих.
    """
    return {
        "size": max(1, size),
        "surplus_food": site.food,
        "food_stock": 0.0,
        "granary_size": GRANARY_PER_SIZE * (max(1, size) + 1),
        "improvements": [True] if capital else [],
        "surplus_shield": site.shields,
        "surplus_trade": site.trade,
        "city_corruption": 0.0,
    }


def citizens_per_turn(surplus: float, size: int, food_cost: float = 2.0) -> float:
    """Доля жителя, которую город набирает за ход при данном излишке еды."""
    return max(0.0, surplus) / growth_box(size)


def size_at_horizon(site: SiteEvaluation, *, turns: int = 15, size: int = 1,
                    food_cost: float = 2.0, stock: float = 2.0) -> tuple[int, float]:
    """Размер города, который был бы на ходу `turns`, если основать сейчас.

    Это и есть контрфактический рост (Axiom 6): основать раньше — значит
    получить `turns` ходов роста. Возвращает (размер, остаток амбара).
    """
    cur = max(1, size)
    surplus = site.food - food_cost * cur
    for _ in range(max(0, turns)):
        stock += surplus
        while stock >= growth_box(cur):
            stock -= growth_box(cur)
            cur += 1
            surplus = site.food - food_cost * cur
    return cur, stock


def counterfactual_growth_sink_per_turn(site: SiteEvaluation | None, vals: dict[str, Any],
                                        *, size: int = 1) -> float:
    """ПЛОСКИЙ прокси стока задержки: «доля жителя за ход × цена жителя».

    Оставлен как запасной путь и как точка сравнения: он не учитывает множители
    площадки (первый и второй множители города), поэтому завышает цену задержки.
    Основной путь — :func:`counterfactual_growth_sink`.

    `W_GROWTH × CITY_POP × DOF_SCALE × (surplus / амбар)` — то есть «сколько
    жителя набирает город за ход» × цена жителя. Если площадка не оценена,
    возвращается пол (`UNDEPLOYED_CARRIER_SINK_PER_TURN`).
    """
    floor = float(vals.get("UNDEPLOYED_CARRIER_SINK_PER_TURN", 0.02))
    if site is None:
        return floor
    food_cost = float(vals.get("FOOD_COST", 2.0))
    rate = (float(vals.get("W_GROWTH", 0.35))
            * float(vals.get("CITY_POP", 1.0))
            * float(vals.get("DOF_SCALE", 10.0))
            * citizens_per_turn(site.food_surplus, size, food_cost))
    return max(floor, rate)


def counterfactual_growth_sink(site: Optional[SiteEvaluation], vals: dict[str, Any],
                               value_of_size, *, size: int = 1) -> float:
    """Цена задержки за ход — прирост ценности города, посчитанной ФОРМУЛОЙ ГОРОДА.

    `value_of_size(s)` даёт ценность города размера `s` на этой площадке (вызывающий
    передаёт функцию, потому что формула города живёт в экстракторе и знает
    множители площадки: еду, щиты, торговлю). Тогда

        сток/ход = W_GROWTH × (ценность(размер на горизонте) − ценность(сейчас)) / горизонт

    Это и есть «основать раньше — получить N ходов роста» (Axiom 6) без плоского
    допущения «житель стоит CITY_POP × DOF_SCALE»: рост считается тем же кодом,
    что и настоящий город, поэтому улучшения, еда и торговля площадки влияют на
    цену задержки. Если город на горизонте не вырос, терять нечего — возвращается пол.
    """
    floor = float(vals.get("UNDEPLOYED_CARRIER_SINK_PER_TURN", 0.02))
    if site is None or not site.viable:
        return floor
    horizon = max(1, int(vals.get("GROWTH_HORIZON_TURNS", 15)))
    food_cost = float(vals.get("FOOD_COST", 2.0))
    grown, _ = size_at_horizon(site, turns=horizon, size=size, food_cost=food_cost)
    if grown <= size:
        return floor
    gain = max(0.0, float(value_of_size(grown)) - float(value_of_size(size)))
    return max(floor, float(vals.get("W_GROWTH", 0.35)) * gain / horizon)


def best_sites(map_obs: dict[str, Any], units: Iterable[dict[str, Any]], *,
               size: int = 1, vals: dict[str, Any] | None = None) -> list[SiteEvaluation]:
    """Оценки площадок вокруг переданных носителей (по одной на носителя)."""
    out: list[SiteEvaluation] = []
    for u in units:
        x, y = u.get("x"), u.get("y")
        if x is None or y is None:
            continue
        out.append(evaluate_site(map_obs, int(x), int(y), size=size, vals=vals))
    return out
