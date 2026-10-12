"""Кандидаты для прогноза: какие действия вообще существуют в этом состоянии.

Ключевое отличие от прежнего генератора: кандидат несёт **не только дельту**, но и
состояние, которое он создаёт. Именно так прогноз видит последствия.

Про движение — измеренный факт вместо прежней догадки. Раньше здесь стояло, что
`goto_N` не несёт координат и потому движение моделируется семейством. Отозвано
2026-09-27: `ActGoto` строит имя как `"goto_%i" % dir8`, а команда — `ORDER_MOVE` с
этим же dir8, то есть **шаг в направлении N** (0=СЗ…7=ЮВ). Цель вычислима
(`live.direction_target`), поэтому на живом пути каждый шаг несёт своё настоящее имя
(`goto_3`) и свою клетку. Семейство по `reach` остаётся только там, где меню действий
нет вовсе (синтетика в тестах) — и там оно честно называется верхней границей.
"""
from __future__ import annotations
import os

import math
from dataclasses import dataclass, field
from typing import Callable

from . import transitions as tr
from .state import ForecastState


@dataclass
class Valuations:
    """Оценки, которые прогноз берёт из модели. Все — в шкале ядра (0…1].

    Внедряются функциями, поэтому сам прогноз не знает ни про CivRealm, ни про
    карту: его можно проверять синтетикой, без живого стенда.
    """

    #: клетки, достижимые юнитом за ход (включая нераскрытые — их ценность даст
    #: среднее по раскрытым, и именно это создаёт мотивацию к разведке)
    reach: Callable[[str], list[tuple[int, int]]]
    #: годится ли площадка под город (гейт по еде)
    site_viable: Callable[[tuple[int, int]], bool]
    #: DoF города размера 1 на площадке (шкала ядра)
    city_dof: Callable[[tuple[int, int]], float]
    #: id городов, которыми можно распоряжаться
    city_ids: Callable[[], list[str]]
    #: что может построить город: [(тип, DoF, ходов)]
    productions: Callable[[str], list[tuple[str, float, int]]]
    #: что можно исследовать: [(технология, DoF, ходов)]
    techs: Callable[[], list[tuple[str, float, int]]]
    #: работы на клетке: [(действие, ΔDoF, id города или None)]
    works: Callable[[tuple[int, int]], list[tuple[str, float, str | None]]]
    #: носитель ли населения (только ему основание и цена площадки)
    is_carrier: Callable[[str], bool]
    #: Доля сохраняемой стоимости, которую несёт ШАГ к цели (§10.38, V2):
    #: `(unit_id, откуда, куда) -> R / N`, где `R` — измеренная цена простоя юнита
    #: в опциях за ход, `N` — шагов до цели. `None` — состояние без провода
    #: (синтетика): тогда у шага остаётся только раскрытие, как раньше.
    goal_credit: Callable[[str, tuple[int, int], tuple[int, int]], float] | None = None
    #: предложенные серверу шаги юнита: [(имя `goto_<dir8>`, клетка назначения)].
    #: Задаётся на живом пути, где есть меню действий. `None` — состояние без
    #: провода (синтетика в тестах): тогда движение берётся семейством по `reach`,
    #: и это ЧЕСТНО называется верхней границей. Отозвано 2026-09-27: раньше здесь
    #: стояло, что координат у `goto_N` нет вовсе; измерено по исходнику стенда,
    #: что `N` — это dir8, поэтому на живом пути шаг имеет ТОЧНУЮ цель.
    moves: Callable[[str], list[tuple[str, tuple[int, int]]]] | None = None
    #: что город может поставить из УЛУЧШЕНИЙ: [(имя, Δопций ГОРОДА, ходов,
    #: доля времени)]. Доля времени — объявленное правило для построек
    #: (§10.25.4): `(H − срок)/H` вместо `γ^срок`, потому что срок здания здесь
    #: измерен в 1 щит/ход, и `γ^30` говорит «ничего» там, где честный ответ —
    #: «мало». `None` — обычный дисконт.
    #: Улучшение не создаёт сущность — оно растит опции того же города (иначе
    #: здание считалось бы живым и индекс рос бы дважды). Пустой список по
    #: умолчанию: семейство подключается там, где оно есть (живой провод).
    improvements: Callable[[str], list[tuple[str, float, int, float | None]]] = \
        lambda _city: []
    #: переводы жителя между клетками: [(действие `city_work_…`, Δопций ГОРОДА)].
    #: Цена — формулой города и замером подтверждена (§10.25.4); задержки нет,
    #: потому что выход клетки меняется сразу.
    tiles: Callable[[str], list[tuple[str, float]]] = lambda _city: []
    #: покупка производства: [(действие, тип предмета, опции, цена в золоте)]. Само
    #: золото в модели не оценено (это решение Andy, §10.25.1): доступность проверяет
    #: поставщик, а кандидат отличается от производства только задержкой (0 вместо
    #: срока) — то есть покупка выигрывает ровно дисконт, который прогноз иначе платит.
    buys: Callable[[str], list[tuple[str, str, float, float]]] | None = None
    #: ценность раскрытия клетки, в единицах индекса (разрыв Дженсена по
    #: измеренному разбросу ценностей клеток, `info.py`). Ноль для уже раскрытой
    #: клетки — разглядывать в ней нечего.
    info_gain: Callable[[tuple[int, int]], float] = lambda _tile: 0.0
    #: МОЖЕТ ли сервер это предложить прямо сейчас: (вид, сущность, имя) → bool.
    #: Обязательный фильтр, а не украшение: модель площадки не знает правил стенда
    #: (например `citymindist = 2` — город нельзя основать рядом с другим), и без
    #: этой проверки прогноз выбирает действия, которых сервер не предлагает.
    #: Урок живой: первый прогон 25 раз подряд выбрал `build_city` юниту, которому
    #: он недоступен, и сторона простояла весь матч.
    allowed: Callable[[str, str, str], bool] = lambda _kind, _actor, _name: True
    #: Решил ли этот актёр в ЭТОМ ходу. Правило «один актёр — одно решение за ход»
    #: (конвенция civrealm); без него прогноз, вызванный второй раз за тот же ход,
    #: предлагает ход уже решившему актёру, раннер его отбрасывает — и счётчики
    #: решений перестают соответствовать тому, что ушло на провод.
    excluded: Callable[[str, str], bool] = lambda _ctrl, _actor: False


@dataclass
class Candidate:
    """Кандидат: действие, его преемник и немедленный эффект."""

    action: tuple[str, str, str]     # (ctrl, actor, name) — как на проводе
    effect: tr.Effect
    kind: str = ""                   # move | found | produce | research | work
    score_hint: float = 0.0          # для порядка ветвления (не для решения)
    extra: dict = field(default_factory=dict)


def tile_value(tile: tuple[int, int], vals: Valuations, *, carrier: bool) -> float:
    """Ценность клетки для того, кто на неё встанет (шкала индекса).

    У носителя — логарифм опций города на площадке; у остальных — только цена
    раскрытия. Оба слагаемых в одной шкале, иначе сравнение клеток было бы
    сравнением опций с логарифмами.
    """
    score = 0.0
    if carrier and vals.site_viable(tile):
        dof = float(vals.city_dof(tile))
        if dof > 1.0:
            score += math.log(dof)
    score += float(vals.info_gain(tile))
    return score


def _best_destination(state: ForecastState, unit_id: str, vals: Valuations,
                      *, max_moves: int) -> tuple[tuple[int, int] | None, float, float]:
    """Лучшая достижимая клетка для юнита: (клетка, её ценность, ценность текущей).

    Движение «в никуда» ценности не имеет и кандидатом не становится (иначе агент
    ходил бы без причины). Это путь БЕЗ меню действий (см. `Valuations.moves`).
    """
    here = state.positions.get(unit_id)
    if here is None:
        return None, 0.0, 0.0
    carrier = bool(vals.is_carrier(unit_id))
    current = tile_value(here, vals, carrier=carrier)
    tiles = [t for t in vals.reach(unit_id) if (int(t[0]), int(t[1])) != here]
    if not tiles:
        return None, 0.0, current
    scored = sorted(((tile_value(t, vals, carrier=carrier), t) for t in tiles),
                    key=lambda kv: kv[0], reverse=True)
    best_value, best_tile = scored[0]
    return (int(best_tile[0]), int(best_tile[1])), best_value, current


_MOVE_DIAG: list = []


def move_diag() -> dict:
    """Диагностика последнего вызова `candidates()` по семейству движения (§10.34)."""
    return _MOVE_DIAG[-1] if _MOVE_DIAG else {}


def candidates(state: ForecastState, vals: Valuations, *,
               max_moves: int = 3) -> list[Candidate]:
    """Все действия, которые прогноз считает возможными в этом состоянии.

    Порядок ветвления задаётся `score_hint` (предварительная оценка), но решение
    принимает поиск по всей глубине — предварительная оценка не является вердиктом.
    """
    out: list[Candidate] = []

    # 1. Основание города: носитель стоит на годной площадке.
    for unit_id, pos in list(state.positions.items()):
        if not vals.is_carrier(unit_id):
            continue
        tile = (int(pos[0]), int(pos[1]))
        if not vals.site_viable(tile):
            continue
        effect = tr.found_city(state, unit_id, city_dof=float(vals.city_dof(tile)))
        out.append(Candidate(action=("unit", unit_id, "build_city"),
                             effect=effect, kind="found",
                             score_hint=effect.delta,
                             extra={"tile": tile}))

    # 2. Движение. На живом пути — ТОЧНЫЕ шаги: каждая предложенная сервером
    #    команда `goto_<dir8>` имеет вычисляемую цель, поэтому кандидат несёт своё
    #    имя и свою клетку (никакой подстановки «первой попавшейся» на проводе).
    #    Без меню (синтетика) — семейство по `reach`, и это верхняя граница.
    # Диагностика семейства движения (§10.34): движение в прогнозе исчезло после
    # основания города, хотя сервер предлагает по 8 шагов каждому юниту. Без чисел
    # «кандидатов нет» неотличимо от «кандидатов не создаёт наш фильтр».
    move_diag: dict = {"единиц": 0, "предложено_шагов": 0, "отброшено_по_ценности": 0,
                       "оставлено": 0, "без_шагов": 0, "текущая_ценность": [],
                       "шаги": []}
    for unit_id in list(state.positions):
        here = state.positions.get(unit_id)
        carrier = bool(vals.is_carrier(unit_id))
        current = tile_value((int(here[0]), int(here[1])), vals, carrier=carrier) \
            if here is not None else 0.0
        steps = vals.moves(unit_id) if vals.moves is not None else []
        move_diag["единиц"] += 1
        move_diag["текущая_ценность"].append(round(float(current), 3))
        if not steps:
            move_diag["без_шагов"] += 1
        if steps:
            move_diag["предложено_шагов"] += len(steps)
            for name, target in steps:
                tile = (int(target[0]), int(target[1]))
                value = tile_value(tile, vals, carrier=carrier)
                gain = float(vals.info_gain(tile))
                # ПРОГРЕСС К ЦЕЛИ (§10.38, V2): доля R/N измеренной цены простоя
                # юнита. Без него шаг по раскрытой клетке имеет дельту 0 и в порядке
                # ветвления всегда ниже производства — измерено: ключ 1.1 против 1.7–3.0.
                progress = 0.0
                if vals.goal_credit is not None and here is not None:
                    try:
                        progress = max(0.0, float(vals.goal_credit(
                            unit_id, (int(here[0]), int(here[1])), tile)))
                    except Exception:  # noqa: BLE001 - диагностика не рушит выбор
                        progress = 0.0
                # Числа шага: без них не выбрать вариант правки фильтра — «в туман
                # имеет смысл идти» остаётся мнением, пока не видно value и gain.
                if len(move_diag["шаги"]) < 16:
                    move_diag["шаги"].append({
                        "юнит": unit_id, "куда": tile, "ценность": round(float(value), 3),
                        "раскрытие": round(gain, 3), "прогресс": round(progress, 3),
                        "на_месте": round(float(current), 3),
                        "пройдёт_по_ценности": bool(value > current),
                        "пройдёт_с_раскрытием": bool(value + gain > current),
                    })
                # Ход стоит ценности только если преемник её даёт — ИЛИ если он ведёт
                # к цели (тогда ценность даёт не клетка, а приближение к площадке).
                if value + gain <= current and progress <= 0.0:
                    move_diag["отброшено_по_ценности"] += 1
                    continue
                move_diag["оставлено"] += 1
                effect = tr.move(state, unit_id, tile,
                                 info_gain=float(vals.info_gain(tile)),
                                 progress=progress)
                out.append(Candidate(action=("unit", unit_id, name),
                                     effect=effect, kind="move",
                                     score_hint=(value - current) + progress,
                                     extra={"tile": tile, "value": value,
                                            "direction": name,
                                            "progress": progress}))
            continue
        tile, best_value, current = _best_destination(state, unit_id, vals,
                                                      max_moves=max_moves)
        if tile is None:
            continue
        # Ход стоит ценности только если преемник её даёт: нулевое движение не
        # предлагается — иначе агент «ходит» без причины.
        if best_value <= current:
            continue
        effect = tr.move(state, unit_id, tile,
                         info_gain=float(vals.info_gain(tile)))
        out.append(Candidate(action=("unit", unit_id, "goto"),
                             effect=effect, kind="move",
                             score_hint=best_value - current,
                             extra={"tile": tile, "value": best_value}))

    # 3. Производство: у города появляются будущие юниты.
    for city_id in vals.city_ids():
        if city_id not in state.dof:
            continue
        for unit_type, unit_dof, turns in vals.productions(city_id):
            effect = tr.produce(state, city_id,
                                unit_id=f"{city_id}:{unit_type}",
                                unit_dof=float(unit_dof), turns=int(turns))
            out.append(Candidate(action=("city", city_id, f"produce_{unit_type}"),
                                 effect=effect, kind="produce",
                                 score_hint=effect.delta,
                                 extra={"turns": turns, "type": unit_type}))

    # 3b. Покупка производства: предмет завершается СЕЙЧАС, за золото.
    #     Отличие от производства ровно одно — задержка 0 вместо срока, поэтому
    #     дисконт не съедает вклад. Цена золота измерена (`= buy_cost`), а само
    #     золото в модели не оценено: ограничение — только доступность (её проверяет
    #     живой поставщик `vals.buys`, и он же отдаёт цену для отчёта).
    if vals.buys is not None:
        for city_id in vals.city_ids():
            if city_id not in state.dof:
                continue
            for action_name, type_name, options, gold_cost in vals.buys(city_id):
                if not vals.allowed("buy", city_id, action_name):
                    continue
                if vals.excluded("city", city_id):
                    continue
                effect = tr.produce(state, city_id,
                                    unit_id=f"{city_id}:{type_name}",
                                    unit_dof=float(options), turns=0)
                out.append(Candidate(action=("city", city_id, action_name),
                                     effect=effect, kind="buy",
                                     score_hint=effect.delta,
                                     extra={"type": type_name,
                                            "gold": gold_cost,
                                            "options": float(options)}))

    # 4. Исследование: технология приносит открытый набор.
    for tech_id, tech_dof, turns in vals.techs():
        effect = tr.research(state, tech_id, tech_dof=float(tech_dof),
                             turns=int(turns))
        out.append(Candidate(action=("tech", "cur_player", tech_name(tech_id)),
                             effect=effect, kind="research",
                             score_hint=effect.delta, extra={"turns": turns}))

    # 4b. Улучшения: опции города растут, новой сущности не появляется.
    for city_id in vals.city_ids():
        if city_id not in state.dof:
            continue
        for name, gain, turns, time_factor in vals.improvements(city_id):
            effect = tr.improve(state, city_id, gain=float(gain), turns=int(turns),
                                time_factor=time_factor)
            out.append(Candidate(action=("city", city_id, f"produce_{name}"),
                                 effect=effect, kind="improve",
                                 score_hint=effect.delta,
                                 extra={"turns": turns, "type": name,
                                        "gain": gain,
                                        "time_factor": time_factor}))

    # 4c. Клетки города: перевод жителя. Задержки нет — выход клетки меняется
    #     сразу; цена считается формулой города (Δопций), замером подтверждена.
    for city_id in vals.city_ids():
        if city_id not in state.dof:
            continue
        if os.environ.get("DOF_NO_TILE_ACTIONS") == "1":
            # Раскладку жителей выбирает городской управляющий СЕРВЕРА тем же
            # `set_default_city_manager`, чьи числа мы портировали, и перекрывает наш приказ
            # на следующем обновлении города (`server/cityturn.c:366`, измерено §13.234:
            # приказ живёт один ход). Ходы на клетки дублируют мир — не предлагаем их вовсе,
            # а освободившиеся ходы идут в основание и дороги. Это ОТДЕЛЬНАЯ ветвь прогноза:
            # общий фильтр решения (`_apply_common_rules`) этих кандидатов не видит.
            continue
        for action, gain in vals.tiles(city_id):
            effect = tr.work(state, city_id=city_id, tile_delta=float(gain),
                             action=action)
            out.append(Candidate(action=("city", city_id, action), effect=effect,
                                 kind="tile", score_hint=effect.delta,
                                 extra={"tile_gain": gain}))

    # 5. Работы: измеренный эффект на клетке (нулевой остаётся нулевым кандидатом,
    #    но с нулевым вкладом — решение о нём принимает поиск, а не генератор).
    for unit_id, pos in list(state.positions.items()):
        for action, tile_delta, city_id in vals.works((int(pos[0]), int(pos[1]))):
            effect = tr.work(state, city_id=city_id,
                             tile_delta=float(tile_delta), action=action)
            out.append(Candidate(action=("unit", unit_id, action),
                                 effect=effect, kind="work",
                                 score_hint=effect.delta,
                                 extra={"city": city_id, "tile_delta": tile_delta}))

    # Обязательный фильтр: прогноз вправе выбирать только то, что сервер реально
    # предлагает. Правила стенда (например минимальная дистанция между городами)
    # модели площадки неизвестны — их знает провод.
    offered = [c for c in out
               if vals.allowed(c.kind, c.action[1], c.action[2])]
    # И только тем, кто в этом ходу ещё не решал: иначе предложение уйдёт актёру,
    # чей ход уже сделан, раннер его отбросит — а счётчики решений разойдутся с тем,
    # что реально ушло на провод (измерено: 61 «действие» при 31 отправленном).
    final = [c for c in offered if not vals.excluded(c.action[0], c.action[1])]
    _MOVE_DIAG.append({**move_diag,
                       "оставлено_после_фильтра":
                       sum(1 for c in final if c.kind == "move")})
    return final


def tech_name(tech_id: str) -> str:
    """`tech_12` → `research_tech_12`: имя действия на проводе."""
    return f"research_{tech_id}"
