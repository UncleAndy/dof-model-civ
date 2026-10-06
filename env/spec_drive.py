"""Живой драйвер решений v0.11: меню → кандидаты → допустимость → выбор ядром → действие.

Зачем отдельный модуль. Сухой пробник (`scripts/v011_decide_probe.py`) показывает, что выбрало бы
ядро, и в мир не отправляет ничего. Здесь то же самое, но выбор **исполняется**:

    Decider.decide(obs, info, turn, prev_obs) -> Optional[tuple]   # аргумент для env.step

Правила, которые соблюдены (и почему):

* **Один переход за вызов** (§9: «evaluates one transition per cycle»). Из выбранного пути в мир идёт
  только первый шаг; ход закрывает вызывающий.
* **Повтор настройки в ходу не порождается** — это правило измерения из `v2`, а не эстетика: без него
  агент переключал производство по семь раз за ход и съедал бюджет юнитов. Исключение делается **при
  порождении** кандидатов, а не удалением из уже объявленного набора: §4.5 — «the candidate set is what
  the Generator proposed», «Every bar is an admissibility condition; nothing is removed».
* **Прошлый выбор не повторяется, если индекс не изменился** — то же измеренное правило `v2`.
* **Действие проверяется по меню мира** перед отправкой: если мира в меню его не предлагает, оно не
  отправляется, и причина называется. Молча «попробовать» нельзя — это была бы выдумка о мире.
* **Объявленный прирост берётся из измерения** (§3.3): таблица живых замеров `env/dof_deltas.py` плюс
  цена основания, считаемая нашими линзами. Догадка о приросте уже один раз обошлась дорого —
  `build_city` был измерен со знаком, обратным прогнозу.

Честная рамка. `Decider` не решает, что такое «полезно»: он объявляет прогноз и отдаёт выбор ядру.
Ядро берёт действие только при `NetDelta > 0`, и «стоять» — законный и ожидаемый исход.
"""
from __future__ import annotations

import collections
from typing import Any, Optional, Sequence

from brain.spec.calculus_core import DOFCalculusCore

from . import spec_graph as G
from . import spec_lenses as L
from . import spec_obs as SO
from . import spec_options as O
from .action_family import family_of
from .action_mapper import FOUNDING_ACTIONS
from .dof_deltas import measured_delta_any_controller

__all__ = ["Decider"]


class Decider:
    """Генератор кандидатов + мост к ядру. Один вызов — не более одного действия."""

    def __init__(self, extractor: Any, own_id: int = 0, with_units: bool = True,
                 core: Optional[Any] = None) -> None:
        self.extractor = extractor
        self.own_id = int(own_id or 0)
        self.with_units = bool(with_units)
        self.core = core if core is not None else DOFCalculusCore()
        self.used_families: set[str] = set()
        self.last_choice: Optional[str] = None
        self.last_index: Optional[float] = None
        #: Последний план **до** применения действия: по нему видно состав империи в тот момент,
        #: когда решение принималось. Нужен, чтобы отличить «город появился от нашего основания»
        #: от «город был и до нас»: после `env.step` наблюдение уже другое, и различие теряется.
        self.last_plan: Optional[dict[str, Any]] = None
        self.log: list[dict[str, Any]] = []

    # ── ход ────────────────────────────────────────────────────────────────────────────
    def new_turn(self) -> None:
        """Начало хода: запрет повтора настройки действует внутри хода."""
        self.used_families = set()

    def plan(self, obs: dict, info: dict, turn: Any,
             prev_obs: Optional[dict] = None) -> dict[str, Any]:
        """Сосчитать кандидатов и выбор ядром. Ничего не отправляет."""
        m = SO.measure_step(obs, info, turn, self.extractor, prev_obs=prev_obs,
                            my_player_id=self.own_id)
        costs = SO.build_cost_index(obs)
        means = L.means_with_income(
            SO.empire_stocks(obs, self.own_id), SO.empire_incomes(obs, self.own_id),
            measured_tech_rate=L.measured_science_rate(prev_obs, obs, self.own_id))
        graph = G.world_graph(m["vectors"], m["fields"], m["dof"], catalogue=m["catalogue"],
                              known_techs=m["known_techs"], raw_menus=m["raw_menus"])
        ctx = G.observation_context(graph, m["dof"])
        st = G.state_with_measured_dof(m["state"], m["dof"])
        player_id = f"player_{self.own_id}"

        def remeasure(vecs, means2=None):
            fresh = {}
            for eid, names in vecs.items():
                kind = L.entity_type_of(eid)
                names = list(names)
                fresh[eid] = L.lens_observation(
                    variety=L.variety_counters(names, SO.disturbances(obs, eid, kind, self.own_id),
                                               SO.powers_of(obs, self.own_id)),
                    requirements=(SO.city_requirements(m["fields"][eid], costs, names,
                                                       m["fields"][eid].get("prod_shield"))
                                  if kind == "city" else {}),
                    constraint=L.constraint_observation(kind, m["fields"][eid]))
            return {eid: met.current_dof
                    for eid, met in L.measure(fresh, means if means2 is None else means2).items()}

        deciders = [player_id] + sorted(e for e in m["vectors"] if e.startswith("city_"))
        if self.with_units:
            deciders += sorted(e for e in m["vectors"] if e.startswith("unit_"))
        production = {e: float(m["fields"][e].get("prod_shield") or 0.0)
                      for e in m["fields"] if e.startswith("city_")}
        standing = {e: float(m["fields"][e]["turns_to_prod_complete"])
                    for e in m["fields"] if e.startswith("city_")
                    and m["fields"][e].get("turns_to_prod_complete") is not None}
        st.deadlines = O.budget_deadlines(deciders)
        st.resources = O.resource_observations(means)
        tech = ((obs.get("player") or {}).get(str(self.own_id)) or {})
        founding_rows: list[dict[str, Any]] = []

        def hypothetical_city_dof(uid: str) -> tuple[Optional[float], str]:
            """DoF города размера 1, посчитанный нашими линзами (клетка в счёт не входит).

            Меню будущего города берётся из опубликованного каталога цен, выход щитов неизвестен —
            и не подставляется нулём: требование считается без него, а причина это называет.
            """
            names = sorted(costs or {})
            if not names:
                return None, "каталог цен пуст — город нечем измерить (мир ещё не публикует цены)"
            city_fields = {"size": 1, "prod_shield": None, "shield_stock": 0}
            obs_lens = L.lens_observation(
                variety=L.variety_counters(names, [], SO.powers_of(obs, self.own_id)),
                requirements=SO.city_requirements(city_fields, costs, names, None),
                constraint=L.constraint_observation("city", city_fields))
            met = L.measure({"city_будущий": obs_lens}, means)
            return (float(met["city_будущий"].current_dof),
                    "город по каталогу, prod_shield неизвестен")

        def measured(eid: str, action: str) -> Optional[float]:
            """§3.3: объявленный прогноз. Замер имеет приоритет над пересчётом линз."""
            name = str(action)
            if any(name.startswith(a) for a in FOUNDING_ACTIONS):
                city_dof, why = hypothetical_city_dof(eid)
                have = (m["dof"] or {}).get(str(eid))
                if city_dof is None or have is None:
                    founding_rows.append({"unit": str(eid), "прирост": None, "причина": why,
                                          "каталог_цен": len(costs or {})})
                    return None
                value = float(city_dof) - float(have)
                founding_rows.append({"unit": str(eid), "doF_поселенца": float(have),
                                      "doF_города": float(city_dof), "прирост": value,
                                      "причина": why, "каталог_цен": len(costs or {})})
                return value
            return measured_delta_any_controller(name)

        options = O.build_options(m["vectors"], m["raw_menus"], m["catalogue"], m["known_techs"],
                                  graph, remeasure, only=deciders, costs=costs, means=means,
                                  production=production, standing=standing,
                                  tech_price=tech.get("researching_cost"),
                                  tech_progress=tech.get("bulbs_researched"),
                                  tech_rate=L.measured_science_rate(prev_obs, obs, self.own_id),
                                  tech_target=tech.get("researching"),
                                  measured=measured)
        # Правила `v2`, применённые ПРИ ПОРОЖДЕНИИ (§13.24, п.7): повтор настройки в ходу и повтор
        # прошлого выбора при неизменном индексе — не порождаем, а не удаляем из набора.
        cur_index = float(m["index"])
        skip = set(self.used_families)
        if self.last_choice is not None and self.last_index is not None \
                and abs(cur_index - self.last_index) < 1e-12:
            skip.add(self.last_choice)
        options = [o for o in options
                   if family_of(str(o.option_id).split(":", 1)[-1]) not in skip]

        winner, rows, barred = O.decide(self.core, st, options, ctx)
        bars = collections.Counter(str(r.get("barred_by")) for r in rows if r.get("barred_by"))
        kind_count = collections.Counter(L.entity_type_of(e) for e in m["vectors"])
        return {"ход": turn, "индекс": cur_index, "средства_energy": means.get("energy", 0.0),
                "состав": dict(sorted(kind_count.items())),
                "кандидатов": len(options), "выбор": getattr(winner, "option_id", None),
                "прирост": (winner.flat_delta() if winner is not None else None),
                "барьеры": dict(bars.most_common(4)), "основание": founding_rows,
                "info_меню": (info or {}).get("available_actions") or {}}

    def env_action(self, option_id: Any, info: dict) -> Optional[tuple]:
        """`unit_104:build_city` → `("unit", "104", "build_city")`, но только если мир его предлагает."""
        text = str(option_id or "")
        if ":" not in text:
            return None
        entity_id, action = text.split(":", 1)
        ctrl = L.entity_type_of(entity_id)
        actor = entity_id.split("_", 1)[-1]
        avail = (info or {}).get("available_actions") or {}
        for ctrl_key, actors in avail.items():
            if str(ctrl_key) != ctrl:
                continue
            for actor_key, names in (actors or {}).items():
                if str(actor_key) not in (actor, entity_id):
                    continue
                if str(action) in (names or {}):
                    return (ctrl_key, actor_key, action)
        return None

    def decide(self, obs: dict, info: dict, turn: Any,
               prev_obs: Optional[dict] = None) -> Optional[tuple]:
        """Выбрать одно действие. `None` — ядро оставило систему на месте (это законный итог)."""
        planned = self.plan(obs, info, turn, prev_obs=prev_obs)
        self.last_plan = planned
        self.log.append({k: v for k, v in planned.items() if k != "info_меню"})
        winner = planned.get("выбор")
        if winner is None:
            self.last_choice, self.last_index = None, planned["индекс"]
            return None
        action = self.env_action(winner, info)
        if action is None:
            planned["не_отправлено"] = "мира в меню этого действия нет — не отправляю"
            return None
        self.used_families.add(family_of(str(action[2])))
        self.last_choice = family_of(str(action[2]))
        self.last_index = planned["индекс"]
        return action
