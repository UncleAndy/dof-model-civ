"""Агент v2: один ход = наблюдение → граф → пути → DOF-фильтр → действие → запись эффекта.

Собирает все системы вместе и не содержит собственной политики: выбор делает calculus, а он
опирается на индекс спеки и на измеренную проекцию. Пока проекция пуста (начало игры), выбор
падает на пробный путь — то есть агент **исследует**, а не угадывает.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import calculus, effects, experiment, generator, sensors
from .generator import Step
from .executor import Journal, to_env_action
from .families import action_family
from .store import KnowledgeStore


def _foreign_summary(graph) -> dict:
    """Что мы ВИДИМ из чужого: сколько и с какой атакой. Нужно, чтобы отличить
    «угрозы нет» от «угрозы не видно».

    Считаем ДВА независимых канала: секцию `unit` (паспорта видимых юнитов) и карту мира
    `map.unit_owner` (клетка -> владелец юнита). Если второй показывает чужого, а первый нет —
    значит ошибка в сенсоре, а не «на карте никого».
    """
    from . import threat
    units = [e for e in graph.by_kind("unit") if not e.is_own]
    by_attack: dict[str, int] = {}
    for e in units:
        a = e.attrs.get("type_attack_strength")
        by_attack[str(a)] = by_attack.get(str(a), 0) + 1
    owners = dict((graph.world or {}).get("владельцы_юнитов") or {})
    return {"юнитов": len(units), "по_атаке": by_attack,
            "угроз": len(threat.threats(graph)),
            "владельцы_по_карте": owners}


class Agent:
    def __init__(self, store_path: str | Path, trace_path: str | Path | None = None,
                 avoid=None, growth_path: str | Path | None = None) -> None:
        self.store = KnowledgeStore(store_path)
        self.avoid = avoid
        self.journal = Journal(trace_path or (Path(store_path).parent / "traces.jsonl"))
        #: Замер роста города: на каждом ходу пишем (размер, число предложенных переходов,
        #: число разрешённых позиций постройки). Нужен, чтобы ОТВЕТИТЬ ЗАМЕРОМ на вопрос
        #: «растёт ли набор возможностей города вместе с городом», а не предположить это.
        self.growth_path = Path(growth_path) if growth_path else None
        self._growth_seen: set = set()
        #: Действующий ДЛИТЕЛЬНЫЙ ОПЫТ (прирост знания на дистанции, см. experiment.py).
        self._experiment = None
        self._pending = None          # шаг, отправленный в среду
        self._before = None           # снимок состояния до шага
        self._turn: Optional[int] = None
        self._last_choice: Optional[tuple] = None   # (контроллер, актор, семейство)
        self._last_index: Optional[float] = None    # индекс на момент прошлого выбора

    # ---------------------------------------------------------------- решение
    def decide(self, obs: dict, info: dict, own_id: int,
               used_actors: Optional[set] = None) -> Optional[tuple]:
        """Вернуть аргумент для `env.step` или None (закрыть ход)."""
        used_actors = used_actors or set()
        available = (info or {}).get("available_actions") or {}
        menu = sensors.read_menu(available)

        # 1) знание: влить наблюдение (наборы возможностей накапливаются)
        self.store.observe(obs, available, own_id)
        g = self.store.graph
        self._record_growth(g, menu)
        turn = (info or {}).get("turn")

        # 1.5) длящийся опыт: продолжаем или закрываем (E3: прерывается, если действие отпало)
        if self._experiment is not None:
            exp = self._experiment
            opts_now = sensors.valid_options(menu, exp.ctrl, exp.actor)
            elapsed = (turn - exp.started_turn) if isinstance(turn, int) else 0
            gone = exp.action not in opts_now
            if elapsed >= exp.turns or gone:
                res = experiment.finish(g, exp, menu, interrupted=gone)
                self.journal.write({"ход": turn, "опыт_закрыт": exp.to_dict(),
                                    "результат": res})
                self._experiment = None
            else:
                if (exp.ctrl, exp.actor) in used_actors:
                    return None          # актор уже действовал в этом ходу
                step = Step(ctrl=exp.ctrl, actor=exp.actor, action=exp.action,
                            reversible=True, variants=1, alternatives=[exp.action])
                self._pending = step
                self._before = effects.snapshot(obs, own_id)
                self._turn = turn
                self.journal.write({"ход": turn, "опыт": exp.to_dict(),
                                    "продолжение": exp.action})
                return to_env_action(step)

        # 2) генератор: пути и цели без пути
        paths, open_goals = generator.generate(g, menu, own_id, avoid=self.avoid)

        # 3) DOF-фильтр: индекс, NetDelta, выбор
        # Исключаем: (а) акторов, которые уже действовали в этом ходу (конвенция civrealm — одно
        # действие на актора за ход), (б) прошлый выбор, если состояние значимо не изменилось
        # (измерено: без этого агент повторял `set_tech_goal` каждый ход).
        cur_idx = calculus.index(g)["value"]
        exclude = set(used_actors)
        if (self._last_choice is not None and self._last_index is not None
                and cur_idx == self._last_index):
            exclude.add(self._last_choice)
        decision = calculus.evaluate(g, paths, own_id, exclude=exclude)
        chosen = decision.chosen
        step = chosen.steps[0] if chosen is not None else None

        # конвенция civrealm: один актор — одно действие за ход
        if step is not None and (step.ctrl, step.actor) in used_actors:
            decision.trace["reason"] += " | актор уже действовал в этом ходу"
            chosen, step = None, None

        self._pending = step
        self._before = effects.snapshot(obs, own_id)
        self._turn = (info or {}).get("turn")

        declared = None
        if chosen is not None:
            declared = {"ctrl": step.ctrl, "actor": step.actor, "action": step.action}
        elif paths:
            declared = {"ctrl": paths[0].steps[0].ctrl, "actor": paths[0].steps[0].actor,
                        "action": paths[0].steps[0].action}
        self.journal.note(declared, declared if step is not None else None)

        self.journal.write({
            "ход": self._turn, "решение": declared,
            "выбрано": (chosen.to_dict() if chosen is not None else None),
            "путей": len(paths), "целей_без_пути": len(open_goals),
            "причина": decision.trace["reason"],
            "индекс": decision.trace["index_current"],
            "риск": decision.trace.get("риск"),
            "чужое": _foreign_summary(g),
            "кальк_включено": len(decision.trace["calc_included"]),
            "кальк_исключено": decision.trace["calc_excluded"],
            "кандидаты": [{"эффект": c["path"]["effect"], "net_delta": c["net_delta"],
                           "почему": c["why"]} for c in decision.trace["candidates"]],
        })

        if step is None:
            # Нечего делать по индексу и нет одношаговой пробы → ДЛИТЕЛЬНЫЙ ОПЫТ (E4).
            started = experiment.start(g, menu, turn, avoid=self.avoid)
            if started is not None:
                exp, st = started
                if (st.ctrl, st.actor) not in used_actors:
                    self._experiment = exp
                    self._pending = st
                    self._before = effects.snapshot(obs, own_id)
                    self._turn = turn
                    self.journal.write({"ход": turn, "опыт_начат": exp.to_dict()})
                    return to_env_action(st)
            self.journal.empty_turns += 1
            self._last_choice = None
            self._last_index = cur_idx
            return None
        self._last_choice = (step.ctrl, step.actor, action_family(step.action))
        self._last_index = cur_idx
        return to_env_action(step)

    # ---------------------------------------------------------------- эффект
    def _record_growth(self, graph, menu: dict) -> None:
        """Замер: размер города ↔ число предложенных ему переходов."""
        if self.growth_path is None:
            return
        from .sensors import valid_options
        for e in graph.by_kind("city"):
            if not e.is_own:
                continue
            key = (self._turn, e.eid)
            if key in self._growth_seen:
                continue
            self._growth_seen.add(key)
            opts = valid_options(menu, "city", e.eid.split(":")[-1])
            fams = sorted({o.split("_")[0] for o in opts})
            # измеренная связь для базы знаний: «размер города -> сколько переходов предлагают»
            if isinstance(e.attrs.get("size"), int) and opts:
                graph.note_observation("city_size_options",
                                       {"размер": e.attrs["size"], "значение": len(opts)})
            # устойчивая мера (не зависит от окна обёртки): «размер -> позиций постройки»
            if (isinstance(e.attrs.get("size"), int)
                    and isinstance(e.attrs.get("n_buildable"), int)):
                graph.note_observation("city_size_buildable",
                                       {"размер": e.attrs["size"],
                                        "значение": e.attrs["n_buildable"]})
            rec = {"ход": self._turn, "город": e.eid, "размер": e.attrs.get("size"),
                   "переходов_предложено": len(opts),
                   "семейств": len(fams),
                   "позиций_постройки": e.attrs.get("n_buildable"),
                   "еда_прирост": e.attrs.get("surplus_food"),
                   "щиты": e.attrs.get("shield_stock"),
                   "дней_до_постройки": e.attrs.get("turns_to_prod_complete"),
                   "семейства": fams[:8]}
            with self.growth_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def record_outcome(self, obs: dict, own_id: int) -> Optional[dict]:
        """Записать, что изменилось после шага (реального действия или закрытия хода)."""
        if self._before is None:
            return None
        after = effects.snapshot(obs, own_id)
        changes = effects.diff(self._before, after)
        step = self._pending
        if step is not None:
            ctrl, fam = step.ctrl, action_family(step.action)
            example = {"действие": step.action, "актор": step.actor, "ход": self._turn}
            # Помечаем исполненное семейство — и у юнита (и его типа), и у канала.
            if ctrl == "unit":
                e = self.store.graph.entity(f"unit:{step.actor}")
                if e is not None:
                    ex = set(e.attrs.get("exercised_families") or [])
                    ex.add(fam)
                    e.attrs["exercised_families"] = sorted(ex)
                    te = self.store.graph.entity(f"unit_type:{e.name}") if e.name else None
                    if te is not None:
                        ex2 = set(te.attrs.get("exercised_families") or [])
                        ex2.add(fam)
                        te.attrs["exercised_families"] = sorted(ex2)
            else:
                ce = self.store.graph.entity(f"controller:{ctrl}:{step.actor}")
                if ce is not None:
                    ex = set(ce.attrs.get("exercised_families") or [])
                    ex.add(fam)
                    ce.attrs["exercised_families"] = sorted(ex)
        else:
            ctrl, fam = "turn", "advance"
            example = {"действие": "закрытие хода", "ход": self._turn}
        self.store.graph.record_effect(ctrl, fam, changes, example)
        self._pending = None
        self._before = None
        return changes

    # ---------------------------------------------------------------- партия
    def end_game(self, save: bool = True) -> None:
        self.store.end_game(save=save)