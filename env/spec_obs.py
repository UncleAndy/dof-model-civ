"""Замер шага по НАБЛЮДЕНИЮ мира — помощники, общие для прогона на фикстуре и живого прогона.

Зачем отдельный модуль: живой прогон обязан мерить **тем же кодом**, что и прогон на записанных
наблюдениях, иначе числа расходятся не по существу, а по копии. Поэтому здесь лежит ровно то, что
нужно обоим: цены построек из публикуемых спек, требования города, запасы и доходы державы, возмущения
и чужие державы, и одна сводная функция `measure_step`, возвращающая всё, что нужно отчёту.

Всё, что здесь считается, объявлено в `env/config.py` и `env/spec_lenses.py`; модуль только связывает
их с наблюдением. Ничего «своего» тут не появляется.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from env import spec_lenses as L
from env import spec_options as O
from env.config import (SPEC_INCOME_FIELDS, SPEC_MEANS_HORIZON_TURNS,
                        MEASURED_IMPROVEMENT_ACCUMULATION_PER_TURN)


def build_cost_index(obs: Mapping[str, Any]) -> dict[str, float]:
    """Имя → стоимость в щитах, из спек, которые мир публикует у технологий.

    Единственный наблюдённый источник цен: у технологий лежат `sup_units` и `sup_improvements` —
    полные спецификации того, что они открывают, вместе с `build_cost`. Ничего не выдумываем: чего
    нет в спеках — того нет и в ценах.
    """
    index: dict[str, float] = {}
    for tech in (obs.get("tech") or {}).values():
        if not isinstance(tech, dict):
            continue
        for key in ("sup_units", "sup_improvements"):
            specs = tech.get(key)
            if not isinstance(specs, list):
                continue
            for spec in specs:
                if not isinstance(spec, dict):
                    continue
                name = spec.get("name") or spec.get("rule_name")
                cost = spec.get("build_cost")
                if name and cost is not None:
                    index[str(name)] = float(cost)
    return index


def _entity_record(raw: Any, eid: str) -> dict[str, Any]:
    """Запись сущности из секции наблюдения (общий поиск по ключу — `L.section_for`)."""
    key = str(eid).split("_", 1)[1] if "_" in str(eid) else str(eid)
    found = L.section_for(raw, key)
    return dict(found) if isinstance(found, Mapping) else {}


def city_requirements(city_obs: Mapping[str, Any], costs: Mapping[str, float],
                      menu: list[str], production: Optional[float] = None,
                      horizon: float = SPEC_MEANS_HORIZON_TURNS,
                      kinds: Optional[Mapping[str, str]] = None,
                      notes: Optional[list[str]] = None) -> dict[str, float]:
    """Требования города: **платёж за горизонт** по тому, что мир предлагает строить.

    База времени одна и та же у требования и у средств: средства — запас плюс доход за горизонт,
    требование — то, что придётся оплатить за горизонт. Полная цена против однодневного дохода —
    не свойство города, а разные базы времени: `20/7` вместо `7/7`.

    **Правило семейства — проверено ЗАМЕРОМ, а не принято на веру.** `v2` измерил у улучшений **1 щит за
    ход** независимо от `prod_shield` (§10.21.3) и сам предупредил, что при смене стенда правило надо
    перемерить. Мы перемерили (2026-10-07, слот 6000, сид 9780, `scripts/v011_improve_probe.py`): запас
    постройки `Barracks` шёл 18 → 21 → 24 → 27 при выходе города 3 — то есть **скорость улучшения равна
    выходу города**, как у юнитов, а правило `v2` здесь **опровергнуто**. Поэтому отдельная константа не
    нужна: значение `MEASURED_IMPROVEMENT_ACCUMULATION_PER_TURN` остаётся `None` как результат замера, и
    улучшение считается юнитовым правилом — теперь это подтверждённое правило, и причина кладётся в `notes`.
    Если константа когда-нибудь будет заполнена, она перекроет юнитовое правило (ветка выше).
    """
    per_transition: list[dict[str, float]] = []
    for name in menu:
        if not str(name).startswith("produce_"):
            continue
        item = str(name)[len("produce_"):]
        rate, why = production, None
        if (kinds or {}).get(item) == "improvement":
            measured = MEASURED_IMPROVEMENT_ACCUMULATION_PER_TURN
            if measured:
                rate = float(measured)
                why = f"улучшение {item}: своя скорость {measured:g} щитов/ход (замер)"
            else:
                why = (f"улучшение {item}: своя скорость не нужна — ЗАМЕРЕНО 2026-10-07 (слот 6000, сид 9780, "
                       f"`v011_improve_probe.py`), что она равна выходу города; считаем юнитовым правилом "
                       f"({production}). Правило `v2` «1 щит/ход» на нашем стенде опровергнуто")
        if why and notes is not None:
            notes.append(why)
        due = O.payment_due(costs.get(item), rate, horizon)
        if due is not None:
            per_transition.append({"energy": float(due)})
    return L.reduce_requirements(per_transition)


def empire_stocks(obs: Mapping[str, Any], my_player_id: Any = 0) -> dict[str, float]:
    """Запасы агента — наблюдаемые остатки по объявленным ресурсам (только СВОИ города)."""
    own = int(my_player_id or 0)
    shield = food = tech = 0.0
    for city in (obs.get("city") or {}).values():
        if not isinstance(city, dict):
            continue
        if int(city.get("owner", own) or own) != own:
            continue
        shield += float(city.get("shield_stock") or 0.0)
        food += float(city.get("food_stock") or 0.0)
        tech += float(city.get("bulbs") or 0.0)
    gold = 0.0
    for rec in (obs.get("player") or {}).values():
        if isinstance(rec, dict) and "gold" in rec:
            gold = float(rec.get("gold") or 0.0)
            break
    return {"energy": shield, "food": food, "tech": tech, "gold": gold}


def empire_incomes(obs: Mapping[str, Any], my_player_id: Any = 0) -> dict[str, float]:
    """Доход агента за ход — сумма по СВОИМ городам, по объявленным полям дохода."""
    own = int(my_player_id or 0)
    incomes: dict[str, float] = {}
    for res, fields in SPEC_INCOME_FIELDS.items():
        total = 0.0
        for city in (obs.get("city") or {}).values():
            if not isinstance(city, dict):
                continue
            if int(city.get("owner", own) or own) != own:
                continue
            for field in fields:
                if field in city:
                    total += float(city.get(field) or 0.0)
                    break
        incomes[res] = total
    return incomes


def disturbances(obs: Mapping[str, Any], entity_id: str, kind: str,
                 my_player_id: Any = 0) -> list[str]:
    """Способ подсчёта возмущений объявлен в модуле линз (там же и объявление линейки)."""
    return L.active_disturbances(obs, entity_id, kind, my_player_id=int(my_player_id or 0))


def powers_of(obs: Mapping[str, Any], my_player_id: Any = 0) -> list[str]:
    """Чужие державы, о которых сообщает мир — возмущение по объявлению владельца."""
    return L.foreign_powers(obs, my_player_id=int(my_player_id or 0))


def hypothetical_city_dof(costs: Mapping[str, Any], means: Mapping[str, float],
                          obs: Mapping[str, Any], own: int,
                          kinds: Optional[Mapping[str, str]] = None) -> tuple[Optional[float], str]:
    """DoF города размера 1, посчитанный нашими линзами по ОПУБЛИКОВАННОМУ каталогу цен.

    Клетка в счёт не входит (её мера — отдельный вопрос). Выход щитов неизвестен и нулём не
    подставляется: требование считается без него, и причина это называет. Одна процедура на
    всех потребителей — и на объявленную дельту основания, и на способность поселенца.
    """
    names = sorted(costs or {})
    if not names:
        return None, "каталог цен пуст — город нечем измерить (мир ещё не публикует цены)"
    city_fields = {"size": 1, "prod_shield": None, "shield_stock": 0}
    obs_lens = L.lens_observation(
        variety=L.variety_counters(names, [], powers_of(obs, own)),
        requirements=city_requirements(city_fields, costs, names, None, kinds=kinds),
        constraint=L.constraint_observation("city", city_fields))
    met = L.measure({"city_будущий": obs_lens}, means)
    return (float(met["city_будущий"].current_dof),
            "город по каталогу, prod_shield неизвестен")


def production_effects_for_city(fields: Mapping[str, Any], raw_names: Iterable[str],
                                costs: Mapping[str, Any], means: Mapping[str, float],
                                unit_specs: Mapping[str, Mapping[str, Any]],
                                median_combat: float,
                                city_dof_by_catalogue: tuple[Optional[float], str],
                                kinds: Optional[Mapping[str, str]] = None
                                ) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Эффект каждого имени производства: способность − платёж (правило владельца, порог > 0).

    Способность — по объявленному правилу (`production_capability`). Платёж — ТОЙ ЖЕ процедурой,
    что и линза требований: `city_requirements` + `option_blocks` для одного имени, отсюда доля
    `c/p` в [0, 1]. **Скорость накопления — по семейству** (`kinds`): у улучшений она своя, `v2`
    измерил 1 щит/ход, но значение берётся только из нашего замера, иначе причина называется.
    Числа не выдумываются: и способность, и платёж берутся из мира и объявления.
    """
    city_dof, why_city = city_dof_by_catalogue
    prefix = L.SPEC_PRODUCTION_ACTION_PREFIX
    items = sorted({str(n)[len(prefix):] for n in raw_names if str(n).startswith(prefix)})
    surplus = fields.get("surplus_shield")
    if isinstance(surplus, (int, float)) and float(surplus) <= 0.0:
        from .config import SPEC_AB_PROD_GATE       # плечо опыта (в): `off` — прежняя процедура
        if SPEC_AB_PROD_GATE != "off":
            # Правило `v2` §10.99 (замер: ход 1 — чистые 3, DoF города 21.125; застой — 0, DoF 3.0 → 2.0):
            # производство входит в DoF города, только если оно ИДЁТ. Мир публикует чистый прирост щитов
            # (`surplus_shield`); при ≤ 0 разрешённые постройки недостижимы, и приписывать их городу —
            # это богатство, которого у него нет. Отсутствие поля — не ноль (аксиома 5): считаем как раньше.
            # Правило применяется и к «сейчас», и к потолку: один правитель, одно чтение.
            reason = (f"производство НЕ идёт: чистый прирост щитов {float(surplus):g} ≤ 0 — разрешённые "
                      f"постройки недостижимы (правило `v2` §10.99)")
            return {}, [{"имя": it, "эффект": 0.0, "причина": reason} for it in items]
    effects: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    # Способность имени, которого НЕТ в каталоге, не подменяется нулём (аксиома 5; правило владельца
    # «незнание ≠ отсутствие»): берётся медиана способностей известных предметов этого города.
    # Замерено (2026-10-07): из четырёх разрешённых миром имён города два (`Barracks`, `Coinage`) в
    # каталоге технологий отсутствуют, и без этой строки «сейчас» города читалось как 2 вместо 4.
    measured_caps: list[float] = []
    for item in items:
        cap_i, _ = L.production_capability(item, unit_specs.get(item) or {}, median_combat=median_combat,
                                           creating_dof=city_dof, opened_options=0)
        if cap_i is not None:
            measured_caps.append(float(cap_i))
    measured_caps.sort()
    n_caps = len(measured_caps)
    median_cap: Optional[float] = None
    if n_caps:
        median_cap = (measured_caps[n_caps // 2] if n_caps % 2
                      else 0.5 * (measured_caps[n_caps // 2 - 1] + measured_caps[n_caps // 2]))
    for item in items:
        spec = unit_specs.get(item) or {}
        cap, why_cap = L.production_capability(item, spec, median_combat=median_combat,
                                               creating_dof=city_dof, opened_options=0)
        price = costs.get(item)
        if isinstance(price, (int, float)) and price > 0:
            notes: list[str] = []
            req = city_requirements(fields, {item: float(price)}, [f"{prefix}{item}"],
                                    fields.get("prod_shield"), kinds=kinds, notes=notes)
            blocks = L.option_blocks(req, means)
            raw_pay = max((float(c) / float(C) if C else 0.0) for c, C in blocks) if blocks else 0.0
            # Доля требования в средствах нормируется в [0, 1]: > 1 читается как «средств не хватает»,
            # а не как «в шестнадцать раз не хватает» — сравнение с способностью идёт по одной шкале.
            pay = min(1.0, raw_pay)
            why_pay = (f"платёж {price:g} в окне, доля {pay:.4f}"
                       + (f" (сырая доля {raw_pay:.2f} — требование перекрывает средства)" if raw_pay > 1.0 else "")
                       + (" | " + "; ".join(notes) if notes else ""))
        else:
            pay = 0.0
            why_pay = "цена не опубликована — платёж не судится (не подставляется нулём как знание)"
        if cap is None:
            if median_cap is None:
                rows.append({"имя": item, "эффект": None, "причина": f"{why_cap}; {why_pay}"})
                continue
            cap = median_cap
            why_cap = (f"способность не измерена ({why_cap}); взята медиана известных по городу "
                       f"{median_cap:.4f} (n={n_caps}) — незнание не подменяется нулём")
        value = float(cap) - float(pay)
        effects[item] = value if value > 0 else 0.0
        rows.append({"имя": item, "способность": round(float(cap), 4),
                     "платёж": round(float(pay), 4), "эффект": round(value, 4),
                     "причина": f"{why_cap}; {why_pay}"})
    return effects, rows


def calc_set_reason(in_calc: Optional[int], n_measured: int,
                    error: Optional[str] = None) -> Optional[str]:
    """Почему набор расчёта назван именно так (ноль обязан называть своё состояние).

    Возвращает причину, когда набор ПУСТ или не посчитан, и `None`, когда он непустой: пустой
    набор даёт индекс 0.0 — «считать нечего», а не «всё хорошо» (§13.79, ловушка 14).
    """
    if error:
        return f"набор расчёта не посчитан: {error}"
    if in_calc is None:
        return "набор расчёта не посчитан (причина не названа)"
    if in_calc == 0:
        return (f"набор расчёта пуст при {n_measured} измеренных — индекс 0.0 означает "
                f"«считать нечего», а не «всё хорошо»")
    return None


def measure_step(obs: Mapping[str, Any], info: Optional[Mapping[str, Any]], turn: Any,
                 extractor: Any, prev_obs: Optional[Mapping[str, Any]] = None,
                 my_player_id: Any = 0) -> dict[str, Any]:
    """Замер одного шага: линзы по всем сущностям с меню + счёт DoF + индекс.

    Возвращает и `measured` (с ψ по каждому каналу и `current_dof`), и `dof` (нормированный), и
    `counts` — СЧЁТ векторов `V` по сущности: для показаний на кадре нужен счёт (> 1), а не
    нормированная величина, иначе `ln` от неё был бы отрицателен и читался превратно.
    """
    own = int(my_player_id or 0)
    state = extractor.extract(obs, info, turn).state
    menu = L.menu_by_entity((info or {}).get("available_actions") or {})
    costs = build_cost_index(obs)
    means = L.means_with_income(
        empire_stocks(obs, own), empire_incomes(obs, own),
        measured_tech_rate=L.measured_science_rate(prev_obs, obs, own))
    known_gates = {tid for tid, rec in (obs.get("tech") or {}).items()
                   if isinstance(rec, dict) and L.gate_is_open(rec)}
    catalogue = L.catalogue_index(obs.get("tech") or {})
    # Каталог города: меню БЕЗ отсева действий с пустыми параметрами. Мир перечисляет там всё, что
    # город может строить (`produce_<Имя>`), и отсев «пустых» выбрасывал каталог целиком — отсюда
    # 4–5 векторов вместо каталога. Для города каталог — часть предложения мира, не репертуар.
    menu_all = L.menu_by_entity((info or {}).get("available_actions") or {}, valid_only=False)
    unit_specs = L.unit_specs_index(obs.get("tech") or {})
    unit_names_by_id = L.unit_order_index()
    kinds = L.name_kind_map(obs.get("tech") or {})
    median_combat, n_median, why_median = L.median_combat_share(unit_specs)
    v_max_of: dict[str, float] = {}
    city_output: dict[str, dict[str, Any]] = {}
    effect_rows: dict[str, list[dict[str, Any]]] = {}
    bindings: dict[str, Any] = {}
    vectors: dict[str, list[str]] = {}
    fields_of: dict[str, dict] = {}
    raw_menus: dict[str, list[str]] = {}
    tech_skipped = 0
    for eid in sorted(menu):
        kind = L.entity_type_of(eid)
        if kind == "tech":
            tech_skipped += 1               # технология — предмет действия, не сущность
            continue
        raw_names = menu.get(eid, [])
        if kind == "city":
            raw_names = menu_all.get(eid, raw_names)   # каталог города — без отсева «пустых»
        if not raw_names:
            continue                        # сущности без меню не о чем мерить
        raw_menus[eid] = raw_names
        raw = obs.get("dipl" if kind == "diplomacy" else kind, {}) or {}
        fields = _entity_record(raw, eid)
        if kind == "unit":
            # Число оставшихся ходов мир называет по-разному в разных сборках, и от этой величины
            # зависит заморозка `position` (§4.6). Переносим её в поля под одним именем, если она
            # наблюдена; отсутствие остаётся отсутствием и заморозки не создаёт (см. `frozen_variables`).
            for key in ("moves_left", "moves", "move_left", "moves_remaining"):
                if key in fields:
                    fields["moves_left"] = fields[key]
                    break
        effects: Optional[dict[str, float]] = None
        if kind == "city":
            effects, rows_eff = production_effects_for_city(
                fields, raw_names, costs, means, unit_specs, median_combat,
                city_dof_by_catalogue=hypothetical_city_dof(costs, means, obs, own, kinds=kinds),
                kinds=kinds)
            effect_rows[eid] = rows_eff
        allowed_now: Optional[set[str]] = None
        if kind == "city":
            # «Сейчас» читается у МИРА: маска города по размеру (число типов юнитов) плюс то, что
            # мир сам предложил действиями. Имена из маски берутся по `id` типа из каталога.
            mask = fields.get("can_build_unit")
            allowed_now = set(menu.get(eid, ()))
            if isinstance(mask, (list, tuple)):
                allowed_now |= {f"{L.SPEC_PRODUCTION_ACTION_PREFIX}{name}"
                                for uid, name in unit_names_by_id.items()
                                if uid < len(mask) and mask[uid]}
            # Продажа — обратный переход (`v2` §4.1: «постройка → золото, потеря устойчивых опций»),
            # поэтому продать можно только ПОСТРОЕННОЕ. Какие построены, говорит маска мира
            # `improvements` (индекс = id улучшения из `tech.sup_improvements`).
            imask = fields.get("improvements")
            imp_names = L.improvement_id_index(obs.get("tech") or {})
            if isinstance(imask, (list, tuple)) and imp_names:
                allowed_now |= {f"{L.SPEC_SELL_IMPROVEMENT_PREFIX}{imp_names[i]}"
                                for i, v in enumerate(imask) if v and i in imp_names}
        names = L.available_vectors(kind, fields, raw_names, known_gates,
                                    catalogue=catalogue, known_techs=known_gates,
                                    production_effects=effects,
                                    allowed_now=allowed_now)
        vectors[eid] = names
        if kind == "city":
            # `V(максимум)`: тот же счёт, но доступность по технологиям не ограничивает — судится весь
            # каталог. Разрешённое миром множество передаётся и здесь: потолок обязан включать всё, что
            # считает «сейчас» (иначе «сейчас» может превысить потолок — замерено 2026-10-07 у города
            # фикстуры: 126 против 121, потому что `produce_Warriors` даёт маска мира, а каталожный
            # потолок его не видел). Разность — объявленная дельта открытия.
            all_known = set((obs.get("tech") or {}).keys())
            names_max = L.available_vectors(kind, fields, raw_names, known_gates,
                                            catalogue=catalogue, known_techs=all_known,
                                            production_effects=effects, allowed_now=allowed_now)
            v_max_of[eid] = float(L.response_vector_count(names_max))
            # Канал будущего корпусного замера (как у `v2`: `city_output` + `measure_improvement_unlock`):
            # размер, построенные улучшения и число опубликованных предметов — то, из чего наблюдением
            # берётся «насколько улучшение расширяет меню». На одном наблюдении величина не выводится.
            city_output[eid] = {
                "размер": fields.get("size"),
                "улучшения": sorted(imp_names[i] for i, v in enumerate(imask)
                                    if v and i in imp_names) if isinstance(imask, (list, tuple)) else [],
                "публикуемых": len([n for n in raw_names
                                    if str(n).startswith(L.SPEC_PRODUCTION_ACTION_PREFIX)]),
                # Есть ли у нас отображение «позиция маски улучшений → имя» в ЖИВОМ наблюдении
                # (`tech.sup_improvements` с полем `id`). Пусто — гейт продажи работает по
                # предложению мира, и это надо видеть числом, а не догадкой.
                "имён_улучшений_из_каталога": len(imp_names),
                # Диагностика живой формы и канал замера скорости улучшений: что строится и как
                # растёт запас щитов. По ходам из этого берётся Δзапас за ход (правило `v2` §10.21.3
                # обещает 1 щит/ход независимо от `prod_shield` — проверяется НАШИМ замером).
                "поля_есть": {k: (k in fields) for k in
                              ("size", "prod_shield", "shield_stock", "production_kind",
                               "production_value", "improvements", "can_build_unit")},
                "запас_щитов": fields.get("shield_stock"),
                "выход_щитов": fields.get("prod_shield"),
                # Публикуемая коробка роста (§13.77): сколько еды требует следующий размер.
                # Ищем по ИМЕНАМ полей, а не по одному ожидаемому: имя, которого мы не знаем,
                # иначе просто не найдётся. Рядом — полный список опубликованных полей города,
                # чтобы «его нет» было проверяемо, а не предположительно.
                "рост_поля": {str(k): v for k, v in fields.items()
                              if any(w in str(k).lower() for w in
                                     ("food", "gran", "growth", "size"))
                              and not isinstance(v, (dict, list))},
                "имена_полей": sorted(str(k) for k in fields),
                "проект": f"{fields.get('production_kind')}:{fields.get('production_value')}"}
        fields_of[eid] = fields
        variety = L.variety_counters(names, disturbances(obs, eid, kind, own), powers_of(obs, own))
        requirements = (city_requirements(fields, costs, names, fields.get("prod_shield"), kinds=kinds)
                        if kind == "city" else {})   # мир не публикует цены переходов — не выдумываем
        bindings[eid] = L.lens_observation(
            variety=variety,
            requirements=requirements,
            constraint=L.constraint_observation(kind, fields))
    measured = L.measure(bindings, means)
    dof = {eid: m.current_dof for eid, m in measured.items()}
    counts = {eid: float(m.variety_counters.get("V") or 0.0) for eid, m in measured.items()}
    # §4.2/§4.1: набор счёта `calc(S)` и индекс ЯДРА по нему — ОТДЕЛЬНЫМИ числами рядом с нашим
    # `total_index`. Ядру подаётся ДЕЙСТВИТЕЛЬНОЕ наблюдение и состояние с измеренными DoF — тем же
    # способом, что проверен смоуком (`_lens_anchor_smoke.py`): `world_graph` →
    # `observation_context` → `state_with_measured_dof` → `calc_and_index`. Без этого ядро считает
    # случай незнания: ψ = ½ на линзу, DoF = ⅛, `ln ⅛ = −2.0794` (§13.79). Вторая сборка не
    # изобретается. Расхождение здесь — НАБЛЮДЕНИЕ: `index` решения остаётся тем же (§13.80).
    in_calc = core_index = None
    verdict_rows = None
    calc_error = None
    try:
        from env import spec_graph as _G          # ленивый импорт: цикл импортов не создаём
        graph = _G.world_graph(vectors, fields_of, dof, catalogue=catalogue,
                               known_techs=known_gates, raw_menus=raw_menus,
                               strikes=(getattr(extractor, "last_attack_event", {}) or {}
                                        ).get("strikes") or ())
        ctx = _G.observation_context(graph, dof)
        st_calc = _G.state_with_measured_dof(state, dof)
        members, core_index = _G.calc_and_index(st_calc, ctx)
        in_calc = len(members)
        # §13.82: вердикт достижимости по КАЖДОЙ сущности — тем же читателем, что у смоука.
        # Нужен, чтобы различать «выпала вердиктом proven_unreachable» и «уничтожена в игре»:
        # по одной трассе §13.81 эти два случая не разводились.
        verdicts = _G.recoverability(st_calc, ctx)
        verdict_rows = {str(k): {"вердикт": str((v or {}).get("verdict")),
                                 "причина": str((v or {}).get("reason"))[:80]}
                        for k, v in (verdicts or {}).items()}
    except Exception as exc:  # noqa: BLE001
        calc_error = f"{type(exc).__name__}: {str(exc)[:80]}"
    return {"state": state, "measured": measured, "dof": dof, "counts": counts,
            "vectors": vectors, "fields": fields_of, "raw_menus": raw_menus,
            "catalogue": catalogue, "known_techs": known_gates, "tech_skipped": tech_skipped,
            "index": L.total_index(measured),
            "в_расчёте": in_calc,
            "индекс_ядра": (round(float(core_index), 4) if core_index is not None else None),
            "причина_набора": calc_set_reason(in_calc, len(measured), calc_error),
            "вердикты": verdict_rows,
            "v_max": v_max_of, "production_effects": effect_rows,
            "city_output": city_output,
            "median_combat": (median_combat, n_median, why_median)}
