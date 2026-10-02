"""Горизонтная проекция: отложенная отдача на числах, ОПУБЛИКОВАННЫХ МИРОМ.

ЗАЧЕМ. Немедленный индекс слеп к тому, что даёт отдачу через несколько ходов: у исследования
немедленный эффект пуст (идут баллы), у роста города — тоже. Из-за этого агент закрывал ход
(измерено: 255 решений из 477). Горизонт закрывает именно эту слепоту, и **не выдумывая чисел**:

* сколько ходов до технологии — из `player.researching_cost`, `player.bulbs_researched`,
  `player.science` (опубликовано миром), с запасным `rules.base_tech_cost`;
* что технология откроет — из графа мира `tech.unlocks` (ребро `unlocks` на типы и улучшения);
* что это даст — рост **меню города**, а он измерен: `city_buildable_delta` (число разрешённых
  позиций постройки в записи города).

Объявленные решения (до данных):

* **G1. Горизонт = 3 хода** — та же величина, что глубина пути (D2).
* **G2. Отдача за горизонтом не считается** (проект спеки: опция за пределами τ — не вариант),
  но **докладывается** в протоколе как «отложено за горизонт», чтобы это было видно, а не молчало.
* **G3. Цена неизвестной технологии** берётся как `rules.base_tech_cost` (устав мира), а не
  подбирается. Помечается в протоколе.
* **G4. Ничего не добавляется к DoF, кроме роста меню города.** Улучшения и войска учитываются
  только тогда, когда станут отдельными сущностями (город их построит — это уже измерено).
"""
from __future__ import annotations

import math
from typing import Optional

from .families import action_family
from .knowledge import KnowledgeGraph

HORIZON = 3          # глубина ПУТИ (решение D2), не горизонт оценки
TAU_QUANTILE = 0.10  # пессимистичный квантиль для приора (объявлено в §10.60)


def tau(graph: KnowledgeGraph) -> tuple[float, str]:
    """Окно, за которое оценивается отложенная отдача (τ из спеки).

    Измерено, почему это нужно: при горизонте в 3 хода постройка (10–13 ходов) и технология
    (десятки ходов) **всегда** выглядят нулём, и агент закрывает ход (36–37 ходов из 40).
    Решение (B), принятое ранее: τ ограничивает рассуждение и необратимые действия, а не запуск
    обратимых проектов. Поэтому горизонт оценки — τ, а не глубина пути.

    τ = минимум из доступных механизмов; каждый — из опубликованных миром чисел:

    * **приор** — пессимистичная дистанция до соседа по плотности игроков (§10.60);
    * **угроза** — ходов до нашего города для наблюдённого чужого юнита с атакой;
    * **внутренний** — ходов до голода, если город в дефиците еды (`surplus_food <= 0`).
    """
    parts: list[tuple[float, str]] = []

    w = graph.world or {}
    area, n_players = w.get("area"), w.get("n_players")
    if isinstance(area, int) and isinstance(n_players, int) and area > 0 and n_players > 1:
        lam = n_players / float(area)
        r = math.sqrt(-math.log(1.0 - TAU_QUANTILE) / (math.pi * lam))
        parts.append((r, f"приор: r≈{r:.1f} клеток при v=1 (P={n_players}, A={area})"))

    own_cities = [(e.attrs.get("x"), e.attrs.get("y")) for e in graph.by_kind("city") if e.is_own]
    for e in graph.by_kind("unit"):
        if e.is_own or not e.attrs.get("x"):
            continue
        attack = e.attrs.get("attack")
        if not isinstance(attack, (int, float)) or attack <= 0:
            continue
        v = e.attrs.get("move_rate") or 1
        for cx, cy in own_cities:
            if cx is None:
                continue
            d = max(abs(e.attrs["x"] - cx), abs(e.attrs["y"] - cy))
            parts.append((max(1.0, d / float(v)),
                          f"угроза: {e.eid} с атакой {attack:g} в {d} клетках, v={v}"))

    for e in graph.by_kind("city"):
        if not e.is_own:
            continue
        sf = e.attrs.get("surplus_food")
        stock = e.attrs.get("food_stock")
        if isinstance(sf, int) and sf <= 0 and isinstance(stock, int):
            parts.append((max(1.0, float(stock)), f"голод: {e.eid} в дефиците {sf} еды"))

    if not parts:
        return float(HORIZON), "нет данных для τ — беру глубину пути"
    value, why = min(parts, key=lambda p: p[0])
    return value, why


def _horizon(graph: KnowledgeGraph) -> tuple[float, str]:
    return tau(graph)


def tech_id_of(action: str) -> Optional[str]:
    """Идентификатор технологии из имени действия: `research_tech_Banking_7` -> `7`."""
    tail = str(action).rsplit("_", 1)[-1]
    return tail if tail.isdigit() else None


def turns_to_tech(graph: KnowledgeGraph) -> tuple[Optional[int], str]:
    """Сколько ходов до технологии.

    Темп науки берётся **из замера** (`turn/advance` → `player_bulbs_researched_delta` за ход),
    а не из поля `player.science`: измерено, что это поле — доля раскладки, а не баллы за ход,
    и его чтение как темпа давало срок в 1 ход (отсюда был цикл переключений).
    """
    players = [e for e in graph.by_kind("player") if e.is_own]
    if not players:
        return None, "своего игрока в графе нет"
    a = players[0].attrs
    cost = a.get("researching_cost")
    if cost is None:
        cost = (graph.rules or {}).get("base_tech_cost")
        src = "устав мира: base_tech_cost"
    else:
        src = "игрок: researching_cost"
    have = a.get("bulbs_researched") or 0
    rate, rsrc = measured_science_per_turn(graph)
    if not isinstance(cost, (int, float)) or rate is None or rate <= 0:
        return None, f"темп науки не измерен ({src}; {rsrc})"
    left = max(0.0, float(cost) - float(have))
    return int(math.ceil(left / float(rate))), f"{src}, темп {rate:.2f} балла/ход ({rsrc})"


def measured_science_per_turn(graph: KnowledgeGraph) -> tuple[Optional[float], str]:
    """Измеренный темп науки: сколько баллов прибавляет ход мира."""
    rec = graph.effect_of("turn", "advance")
    if not rec:
        return None, "ход мира ещё не наблюдался"
    seen = int(rec.get("seen") or 0)
    d = (rec.get("change_counts") or {}).get("player_bulbs_researched_delta")
    if not seen or d is None:
        return None, "баллы науки в наблюдениях хода мира не встречались"
    rate = float(d) / float(seen)
    if rate <= 0.05:
        return None, f"темп {rate:.2f} балла/ход слишком мал для оценки"
    return rate, f"наблюдено {seen} ход(ов) мира"


def research_gain(graph: KnowledgeGraph, action: str) -> tuple[float, str]:
    """Ожидаемый прирост индекса от выбора технологии.

    **Измеренный вывод: переключение технологии открытий не даёт.** Открытие приходит по
    *завершении* исследования, а завершение не в наших руках — мир исследует сам (измерено:
    `tech_entered_1`, `tech_state_1to2` в эффекте `turn/advance`, при том что агент не завершал
    ни одной технологии своими действиями). Переключение при этом теряет накопленные баллы
    (`player_bulbs_researched_delta: −122` за 115 переключений). Поэтому обещать выигрыш за выбор
    технологии нельзя: это была бы выдуманная отдача. Рычаг существует механически (действие
    предлагается миром), но его **ценность не установлена** — и агент не должен на него тратить ход.

    Открытия попадают в индекс иначе и честно: по факту завершения растёт меню города
    (`city_buildable_delta` — измерено), а это уже учтено как измеренный эффект.

    ΔT (энтропия переключения) берётся **из замера**: если агент уже переключал исследование и
    это стоило баллов (`player_bulbs_researched_delta` в эффекте `tech/research_tech`), потерянные
    баллы превращаются в задержку и сдвигают срок. Так переключение перестаёт быть бесплатным,
    но не потому, что я так решил, а потому что это измерено.
    """
    tid = tech_id_of(action)
    if tid is None:
        return 0.0, "идентификатор технологии не разобран"
    players = [e for e in graph.by_kind("player") if e.is_own]
    cur_id = str(players[0].attrs.get("researching")) if players else None
    if cur_id is not None and tid != cur_id:
        unlocks = graph.out_edges(f"tech:{tid}", kind="unlocks")
        return 0.0, (f"переключение на технологию {tid} открытий не даёт: открытие приходит по "
                     f"завершении, а мир исследует сам (граф: {len(unlocks)} открытий — но "
                     f"обещать их за выбор нельзя)")
    unlocks = graph.out_edges(f"tech:{tid}", kind="unlocks")
    k = len(unlocks)
    if k == 0:
        return 0.0, "граф мира: технология ничего не открывает"

    n, src = turns_to_tech(graph)
    if n is None:
        return 0.0, f"срок неизвестен ({src})"

    # измеренная цена переключения (ΔT): потерянные баллы -> задержка в ходах
    delay, dt_note = 0, ""
    # Уход от текущей технологии теряет НАКОПЛЕННЫЕ баллы (`player.bulbs_researched` —
    # опубликовано миром). Измерено: без этого модель считала выбор технологии мгновенным и
    # агент переключался между двумя технологиями каждый ход (Pottery ↔ Masonry, 50+ раз).
    players = [e for e in graph.by_kind("player") if e.is_own]
    cur_id = str(players[0].attrs.get("researching")) if players else None
    rate_now, _rsrc = measured_science_per_turn(graph)
    if cur_id is not None and tid != cur_id and rate_now:
        bulbs = players[0].attrs.get("bulbs_researched")
        if isinstance(bulbs, (int, float)) and bulbs > 0:
            lost_turns = int(math.ceil(float(bulbs) / float(rate_now)))
            delay += lost_turns
            dt_note += (f"; уход от технологии {cur_id} теряет {bulbs:g} баллов "
                        f"≈ {lost_turns} ход(ов)")
    rec = graph.effect_of("tech", "research_tech")
    if rec:
        b = int((rec.get("change_counts") or {}).get("player_bulbs_researched_delta", 0) or 0)
        if b < 0:
            rate = _science_rate(graph)
            if rate:
                delay = int(math.ceil((-b) / float(rate)))
                dt_note = f"; ΔT из замера: потеряно {-b} баллов ≈ {delay} ход(ов)"
    n_eff = n + delay
    H, hw = _horizon(graph)

    own = [e for e in graph.by_kind("city") if e.is_own and e.dof and e.dof.comparable]
    if not own:
        return 0.0, "открывать нечем: своего города нет (меню постройки некуда расти)"
    vals = sorted(float(e.dof.v) for e in own if e.dof.v and e.dof.v > 0)
    if not vals:
        return 0.0, "у города нет разрешённых позиций постройки"
    v = vals[len(vals) // 2]
    # Скидка на τ, а не отсечение: решение (B) — τ ограничивает рассуждение и необратимые
    # действия, а не запуск обратимых проектов. Поэтому отдача считается долей, уложившейся
    # в окно, и длинный проект не обнуляется (иначе агент закрывал ход 36 ходов из 40).
    frac = min(1.0, H / float(max(1, n_eff)))
    gain = (math.log(v + k) - math.log(v)) * frac
    return gain, (f"за {n_eff} ход(ов) откроется {k} позиций → меню города {v} → {v + k}; "
                  f"в τ={H:.0f} укладывается {frac * 100:.0f}% (граф мира: {src}{dt_note})")


def _science_rate(graph: KnowledgeGraph) -> float:
    players = [e for e in graph.by_kind("player") if e.is_own]
    rate = players[0].attrs.get("science") if players else None
    return float(rate) if isinstance(rate, (int, float)) and rate > 0 else 0.0


def production_gain(graph: KnowledgeGraph, action: str,
                    actor: Optional[str] = None) -> tuple[float, str]:
    """Ожидаемый прирост индекса от постройки в городе за горизонт.

    Срок постройки берётся в объявленном порядке, и ВСЕ три источника — измеренные или
    выведенные из измеренного, ни один не выдуман:

    1. **замер собственного действия**: если агент сам запускал `produce_X`, мир на следующем ходу
       публикует `turns_to_prod_complete` — это и есть срок именно этого варианта (атрибуция по
       нашему действию, а не по догадке);
    2. **публикация мира**: `city.turns_to_prod_complete` (срок текущего производства);
    3. **вывод из измеренных цены и щитов**: `build_cost` из паспорта типа/улучшения и щиты города
       (`prod_shield`, `shield_stock`) дают `ceil((цена − запас) / щиты/ход)`. Помечается как
       выведенное, потому что пошлины/отходы мир не публикует.

    Тип берётся из имени действия (`produce_Settlers` → `Settlers`), его DoF — из накопленного
    набора возможностей, если тип уже наблюдён.
    """
    if not str(action).startswith("produce_"):
        return 0.0, ""
    type_name = str(action)[len("produce_"):]
    eta, src = eta_of(graph, type_name)
    if eta is None:
        return 0.0, ("срок постройки неизвестен и измеренных сроков нет — считать нечем")
    H, hw = _horizon(graph)

    te = graph.entity(f"unit_type:{type_name}")
    dof = None
    dsrc = "тип неизвестен"
    if te is not None:
        fam = te.attrs.get("dof_families")
        if isinstance(fam, int) and fam > 0:
            dof, dsrc = float(fam), f"набор типа {type_name} измерен"
    if dof is None:
        imp, cnt = _impute_unit(graph)
        if imp is None:
            return 0.0, "DoF будущей сущности неизвестен — считать нечем"
        dof, dsrc = imp, f"среднее по своим типам ({cnt})"
    frac = min(1.0, H / float(max(1, eta)))
    gain = math.log(dof) * frac
    why = (f"{src}: за {eta} ход(ов) появится {type_name} → +1 сущность (DoF {dof:g}: "
           f"{dsrc}); в τ={H:.0f} укладывается {frac * 100:.0f}% ({hw})")
    # ЦЕНА ОТКАЗА ОТ НАЧАТОЙ ПОСТРОЙКИ (§10.102): смена варианта теряет вложенные щиты.
    pen, pwhy = switch_penalty(graph, actor, type_name)
    if pen > 0:
        gain -= pen
        why = f"{why} | {pwhy}"
    return gain, why


def switch_penalty(graph: KnowledgeGraph, actor: Optional[str], target: str) -> tuple[float, str]:
    """Цена ОТКАЗА от начатой постройки, в единицах ln(DoF). Всё — из измеренного.

    Замер (§10.102): при смене производства город теряет щиты (`shield_stock` падает). Потеря
    берётся медианой по каналу `produce_switch`; перевод в ценность — структурная формула:

        потеря_в_ходах = потерянные_щиты / чистый_прирост_щитов
        цена = ln(DoF текущей постройки) × min(1, потеря_в_ходах / срок текущей постройки)

    Смысл: теряются щиты, уже вложенные в ТЕКУЩУЮ постройку; если потерянный объём работы больше её
    срока, текущая постройка не состоится никогда — теряется вся её ценность (потолок 1). Пока замер
    не накоплен, цена равна нулю с причиной: величина не выдумывается.
    """
    if actor is None:
        return 0.0, ""
    city = graph.entity(f"city:{actor}")
    if city is None:
        return 0.0, ""
    cur = city.attrs.get("стройка")          # название текущей постройки (знает агент)
    if not cur or cur == target:
        return 0.0, ""
    rows = [r for r in (graph.observed.get("produce_switch") or [])
            if isinstance(r, dict) and r.get("сменил") is True]
    losses = [int(r.get("потеряно") or 0) for r in rows]
    losses = [x for x in losses if x > 0]
    if not losses:
        return 0.0, "потеря щитов при смене производства ещё не измерена"
    losses.sort()
    lost = losses[len(losses) // 2]
    net = city.attrs.get("surplus_shield")
    if not isinstance(net, (int, float)) or net <= 0:
        net = city.attrs.get("prod_shield")
    if not isinstance(net, (int, float)) or net <= 0:
        return 0.0, "чистый прирост щитов неизвестен — перевести потерю нечем"
    eta_cur, _src = eta_of(graph, cur)
    if not eta_cur or eta_cur <= 0:
        return 0.0, f"срок текущей постройки {cur} неизвестен — считать нечем"
    te = graph.entity(f"unit_type:{cur}")
    dof_cur = None
    if te is not None and isinstance(te.attrs.get("dof_families"), int) and te.attrs["dof_families"] > 0:
        dof_cur = float(te.attrs["dof_families"])
    if dof_cur is None:
        imp, _cnt = _impute_unit(graph)
        dof_cur = imp
    if not dof_cur or dof_cur <= 0:
        return 0.0, "DoF текущей постройки неизвестен — считать нечем"
    turns_lost = float(lost) / float(net)
    frac = min(1.0, turns_lost / float(eta_cur))
    penalty = math.log(dof_cur) * frac
    return penalty, (f"отказ от {cur}: потеряно {lost} щитов = {turns_lost:.2f} ход. при {net:g} щит/ход "
                     f"и сроке {eta_cur} → теряется {frac * 100:.0f}% ценности {cur} "
                     f"(−{penalty:.3f})")


def city_crowding_penalty(graph: KnowledgeGraph, actor: str) -> tuple[float, str]:
    """§10.108, штраф 1 — ПЕРЕНАСЕЛЁННОСТЬ: новый город делит работовую зону со своими городами.

    Участок основания — клетка поселенца. Работовая зона города — из опубликованного устава мира
    (`border_city_radius_sq`), геометрия, без коэффициентов. Если доля `ov` работовых клеток нового
    города уже лежит в зоне своего города, новый вносит в индекс `ln(DoF)` только остаток, то есть
    штраф = −ln(1 − ov) (это простая функция доли, число не подбирается). ov=0 → штрафа нет.
    """
    s = graph.entity(f"unit:{actor}")
    if s is None or s.attrs.get("x") is None:
        return 0.0, ""
    x, y = s.attrs["x"], s.attrs["y"]
    xsize = int((graph.world or {}).get("xsize") or 0)
    try:
        r_sq = int((graph.rules or {}).get("border_city_radius_sq") or 0)
    except (TypeError, ValueError):
        r_sq = 0
    if r_sq <= 0:
        return 0.0, "радиус работовой зоны города неизвестен — перенаселённость не оценить"
    own = [c for c in graph.by_kind("city") if c.is_own and c.attrs.get("x") is not None]
    if not own:
        return 0.0, ""
    R = int(math.sqrt(r_sq)) + 1
    offsets = [(dx, dy) for dx in range(-R, R + 1) for dy in range(-R, R + 1)
               if dx * dx + dy * dy <= r_sq]
    total = len(offsets)
    if not total:
        return 0.0, ""
    shared = 0
    for dx, dy in offsets:
        tx = (x + dx) % xsize if xsize else x + dx
        ty = y + dy
        for c in own:
            dxc = abs((c.attrs["x"] - tx + xsize // 2) % xsize - xsize // 2)
            dyc = abs(c.attrs["y"] - ty)
            if dxc * dxc + dyc * dyc <= r_sq:
                shared += 1
                break
    ov = shared / float(total)
    if ov <= 0:
        return 0.0, ""
    ov = min(ov, 0.95)
    pen = -math.log(1.0 - ov)
    return pen, (f"перенаселённость: работовая зона нового города перекрыта со своими городами "
                 f"({len(own)}) на {ov * 100:.0f}% → −{pen:.3f}")


def site_food_penalty(graph: KnowledgeGraph, actor: str, dof_city: Optional[float]) -> tuple[float, str]:
    """§10.108, штраф 2 — ПЛОДОРОДИЕ участка: сможет ли новый город прокормить себя.

    Ожидаемая еда центральной клетки участка берётся из ЗАМЕРА (`terrain_food`: что дают наши
    города на этом террейне); нет замера — средняя по нашим городам (правило «незнание ≠ ноль»).
    Прирост = еда − `food_cost`×1 (население 1). Если прирост > 0 — штрафа нет; если дефицит, город
    не растёт, и его реальный DoF обнуляется (как застой §10.98) → минус полный ln(DoF города).
    """
    s = graph.entity(f"unit:{actor}")
    if s is None or s.attrs.get("x") is None:
        return 0.0, ""
    tile = graph.entity(f"tile:{s.attrs['x']},{s.attrs['y']}")
    terrain = (tile.attrs.get("terrain") if tile is not None else None)
    rows = [r for r in (graph.observed.get("terrain_food") or []) if isinstance(r, dict)]
    same = [float(r["еда"]) for r in rows
            if r.get("terrain") == terrain and isinstance(r.get("еда"), (int, float))]
    if same:
        same.sort()
        exp_food, fsrc = same[len(same) // 2], f"замер: на террейне {terrain} еда {same[len(same) // 2]:g}"
    else:
        allf = sorted(float(r["еда"]) for r in rows if isinstance(r.get("еда"), (int, float)))
        if not allf:
            return 0.0, "еды по участкам ещё не измерено — плодородие не оценить (незнание ≠ ноль)"
        exp_food, fsrc = allf[len(allf) // 2], f"средняя по своим городам: еда {allf[len(allf) // 2]:g}"
    try:
        food_cost = float((graph.rules or {}).get("food_cost") or 2)
    except (TypeError, ValueError):
        food_cost = 2.0
    growth = exp_food - food_cost  # население 1
    if growth > 0:
        return 0.0, f"участок кормится: {fsrc} > {food_cost:g}"
    if not dof_city or dof_city <= 0:
        return 0.0, "участок не прокормит город, но его DoF неизвестен — считать нечем"
    return -math.log(dof_city), (f"участок не прокормит город ({fsrc} ≤ {food_cost:g}) → "
                                 f"город не растёт, DoF обнуляется (−{math.log(dof_city):.3f})")


def _measured_eta(graph: KnowledgeGraph, type_name: str) -> tuple[Optional[int], str]:
    """Измеренный срок: записан наблюдением, когда этот вариант был текущим производством."""
    v = graph.observed_median("produce_eta", {"вариант": type_name})
    if v and v > 0:
        return int(v), f"замер своего запуска ({type_name})"
    return None, ""


def eta_of(graph: KnowledgeGraph, type_name: str) -> tuple[Optional[int], str]:
    """Срок постройки варианта и СТУПЕНЬ его происхождения.

    Ступени: «замер» (мы сами запускали) → «публикация» (текущее производство) → «вывод» (из
    измеренных цены и щитов) → «среднее» (срок неизвестен: среднее по ИЗМЕРЕННЫМ срокам, НЕ ноль)
    → «нет» (считать нечем).

    Почему «среднее», а не «неизвестен — значит не вариант» (правило пользователя: неполные данные
    моделировать средним по известным, НЕ нулём): вариант нельзя вычёркивать только потому, что мы
    о нём не знаем, — иначе военный юнит не будет построен НИКОГДА, и неизвестность не раскроется.
    """
    v, src = _measured_eta(graph, type_name)
    if v is not None:
        return v, f"замер своего запуска ({type_name}); {src}"
    v, src = _published_eta(graph)
    if v is not None:
        return v, f"публикация мира (текущее производство); {src}"
    v, src = _derived_eta(graph, type_name)
    if v is not None:
        return v, src
    def _val(x):
        if not isinstance(x, dict):
            return None
        v = x.get("значение", x.get("ходов"))
        return int(v) if isinstance(v, (int, float)) and v > 0 else None

    known: list[int] = [v for v in (_val(x) for x in (graph.observed.get("produce_eta") or []))
                        if v is not None]
    known += [int(e.attrs["turns_to_prod_complete"]) for e in graph.by_kind("city")
              if isinstance(e.attrs.get("turns_to_prod_complete"), int)
              and e.attrs["turns_to_prod_complete"] > 0]
    if known:
        known.sort()
        med = known[len(known) // 2]
        return med, (f"срок неизвестен → среднее по измеренным ({med} ход., n={len(known)}; "
                     f"незнание ≠ ноль)")
    return None, "нет"


def _published_eta(graph: KnowledgeGraph) -> tuple[Optional[int], str]:
    """Опубликованный миром срок текущего производства города."""
    own = [e for e in graph.by_kind("city") if e.is_own]
    etas = [int(e.attrs["turns_to_prod_complete"]) for e in own
            if isinstance(e.attrs.get("turns_to_prod_complete"), int)
            and int(e.attrs["turns_to_prod_complete"]) > 0]
    if not etas:
        return None, ""
    return min(etas), "публикация мира (текущее производство)"


def _derived_eta(graph: KnowledgeGraph, type_name: str) -> tuple[Optional[int], str]:
    """Срок, ВЫВЕДЕННЫЙ из измеренных цены постройки и щитов города (помечается как выведенный)."""
    cost = None
    for kind in ("unit_type", "improvement"):
        e = graph.entity(f"{kind}:{type_name}")
        c = e.attrs.get("build_cost") if e is not None else None
        if isinstance(c, (int, float)) and c > 0:
            cost = float(c)
            break
    if cost is None:
        return None, ""
    best: Optional[int] = None
    stalled = False
    for e in graph.by_kind("city"):
        if not e.is_own:
            continue
        # ЧИСТЫЙ прирост щитов: содержание юнитов может съесть всю выработку, и тогда мир
        # возвращает «никогда» (FC_INFINITY). Валовой прирост здесь врал бы (замер §10.98).
        shields = e.attrs.get("surplus_shield")
        if shields is None:
            shields = e.attrs.get("prod_shield")
        stock = e.attrs.get("shield_stock")
        if isinstance(shields, (int, float)) and shields <= 0:
            stalled = True
            continue
        if not isinstance(shields, (int, float)) or shields <= 0:
            continue
        left = cost - float(stock if isinstance(stock, (int, float)) else 0)
        eta = max(1, int(math.ceil(left / float(shields))))
        best = eta if best is None else min(best, eta)
    if best is None:
        if stalled:
            return None, "НЕ ИДЁТ: чистый прирост щитов ≤ 0 (содержание юнитов)"
        return None, ""
    return best, "выведено из цены и щитов (мир публикует и то, и другое)"


def _impute_unit(graph: KnowledgeGraph) -> tuple[Optional[float], int]:
    vals = []
    for e in graph.by_kind("unit"):
        if e.is_own and e.dof and e.dof.comparable and e.dof.v and e.dof.v > 0:
            vals.append(float(e.dof.v))
    if not vals:
        return None, 0
    vals.sort()
    return vals[len(vals) // 2], len(vals)


def is_noop(graph: KnowledgeGraph, action: str) -> bool:
    """Действие, которое не меняет состояние, — не путь.

    Объявлено как структурное правило: путь обязан что-то менять. Измерено, что без него агент
    переставлял уже выбранную технологию каждый ход.
    """
    fam = action_family(action)
    players = [e for e in graph.by_kind("player") if e.is_own]
    a = players[0].attrs if players else {}
    if fam == "research_tech":
        tid = tech_id_of(action)
        return tid is not None and str(a.get("researching")) == tid
    if fam == "set_tech_goal":
        tid = tech_id_of(action)
        te = graph.entity(f"tech:{tid}") if tid else None
        return bool(te is not None and te.attrs.get("is_tech_goal"))
    return False