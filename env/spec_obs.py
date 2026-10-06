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
from env.config import SPEC_INCOME_FIELDS, SPEC_MEANS_HORIZON_TURNS


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


def city_requirements(city_obs: Mapping[str, Any], costs: Mapping[str, float],
                      menu: list[str], production: Optional[float] = None,
                      horizon: float = SPEC_MEANS_HORIZON_TURNS) -> dict[str, float]:
    """Требования города: **платёж за горизонт** по тому, что мир предлагает строить.

    База времени одна и та же у требования и у средств: средства — запас плюс доход за горизонт,
    требование — то, что придётся оплатить за горизонт. Полная цена против однодневного дохода —
    не свойство города, а разные базы времени: `20/7` вместо `7/7`.
    """
    per_transition: list[dict[str, float]] = []
    for name in menu:
        if not str(name).startswith("produce_"):
            continue
        due = O.payment_due(costs.get(str(name)[len("produce_"):]), production, horizon)
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
        if not raw_names:
            continue                        # сущности без меню не о чем мерить
        raw_menus[eid] = raw_names
        raw = obs.get("dipl" if kind == "diplomacy" else kind, {}) or {}
        fields = dict(raw.get(eid.split("_", 1)[1], {}) or {})
        if kind == "unit":
            # Число оставшихся ходов мир называет по-разному в разных сборках, и от этой величины
            # зависит заморозка `position` (§4.6). Переносим её в поля под одним именем, если она
            # наблюдена; отсутствие остаётся отсутствием и заморозки не создаёт (см. `frozen_variables`).
            for key in ("moves_left", "moves", "move_left", "moves_remaining"):
                if key in fields:
                    fields["moves_left"] = fields[key]
                    break
        names = L.available_vectors(kind, fields, raw_names, known_gates,
                                    catalogue=catalogue, known_techs=known_gates)
        vectors[eid] = names
        fields_of[eid] = fields
        variety = L.variety_counters(names, disturbances(obs, eid, kind, own), powers_of(obs, own))
        requirements = (city_requirements(fields, costs, names, fields.get("prod_shield"))
                        if kind == "city" else {})   # мир не публикует цены переходов — не выдумываем
        bindings[eid] = L.lens_observation(
            variety=variety,
            requirements=requirements,
            constraint=L.constraint_observation(kind, fields))
    measured = L.measure(bindings, means)
    dof = {eid: m.current_dof for eid, m in measured.items()}
    counts = {eid: float(m.variety_counters.get("V") or 0.0) for eid, m in measured.items()}
    return {"state": state, "measured": measured, "dof": dof, "counts": counts,
            "vectors": vectors, "fields": fields_of, "raw_menus": raw_menus,
            "catalogue": catalogue, "known_techs": known_gates, "tech_skipped": tech_skipped,
            "index": L.total_index(measured)}
