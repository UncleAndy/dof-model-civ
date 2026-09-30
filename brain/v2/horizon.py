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


def production_gain(graph: KnowledgeGraph, action: str) -> tuple[float, str]:
    """Ожидаемый прирост индекса от постройки в городе за горизонт.

    Опирается на опубликованный миром срок `city.turns_to_prod_complete` и на измеренный факт,
    что завершение постройки даёт новую сущность (`unit_new` в эффекте `turn/advance`).
    Тип берётся из имени действия (`produce_Settlers` → `Settlers`), его DoF — из накопленного
    набора возможностей, если тип уже наблюдён.
    """
    if not str(action).startswith("produce_"):
        return 0.0, ""
    type_name = str(action)[len("produce_"):]
    own = [e for e in graph.by_kind("city") if e.is_own]
    etas = [int(e.attrs["turns_to_prod_complete"]) for e in own
            if isinstance(e.attrs.get("turns_to_prod_complete"), int)
            and int(e.attrs["turns_to_prod_complete"]) > 0]
    if not etas:
        return 0.0, "срок постройки неизвестен (нет своего города со сроком)"
    eta = min(etas)
    H, hw = _horizon(graph)

    te = graph.entity(f"unit_type:{type_name}")
    dof = None
    src = "тип неизвестен"
    if te is not None:
        fam = te.attrs.get("dof_families")
        if isinstance(fam, int) and fam > 0:
            dof, src = float(fam), f"набор типа {type_name} измерен"
    if dof is None:
        imp, cnt = _impute_unit(graph)
        if imp is None:
            return 0.0, "DoF будущей сущности неизвестен — считать нечем"
        dof, src = imp, f"среднее по своим типам ({cnt})"
    frac = min(1.0, H / float(max(1, eta)))
    gain = math.log(dof) * frac
    return gain, (f"за {eta} ход(ов) появится {type_name} → +1 сущность (DoF {dof:g}: {src}); "
                  f"в τ={H:.0f} укладывается {frac * 100:.0f}% ({hw})")


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