"""§3.5/§4.9/§4.2: граф мира из наблюдения, вердикт достижимости, множество счёта.

Граф — артефакт **восприятия**: он подаётся циклу и не хранится в состоянии (§4.8).
Без него каждый вердикт `undetermined`, а значит ни одна сущность на известном нуле
не исключается — отказоустойчивое направление: не доказано, значит не удалено.

Модуль ничего не решает сам: узлы, акты и вердикты считает эталонный порт
(`brain/spec/world_graph.py`, `brain/spec/calculus_core.py`). Здесь — только то,
чего эталон знать не может: как игровое наблюдение становится узлами и актами.

Три правила отображения, объявленные в `env/config.py`:

* **акт существует, пока жива его переменная.** Меню — предложение мира, а не
  список возможного: у известной технологии «исследовать её» стоит в меню, а
  действия такого нет (`research` заморожен), и потому известная технология —
  открытая дверь: у неё нет ни вектора реакции, ни акта, ни пути.
* **акт меняет свою цель, а не всегда актора.** Исследование меняет технологию,
  производство — город, перемещение — самого идущего.
* **категория акта — свойство акта**, а `M(S)` объявляет, по каким категориям
  вообще строится путь. Неопознанное действие не создаёт пути.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Mapping, Optional, Sequence

from brain.spec.calculus_core import (
    DOFCalculusCore,
    EntityState,
    ObservationContext,
    SystemStateMatrix,
)
from brain.spec.world_graph import ActEdge, EntityNode, WorldGraph

from .config import (
    SPEC_ACT_EFFECT,
    SPEC_COUNTING_HORIZON_TURNS,
    SPEC_MEANS_CLASS,
    SPEC_PRODUCTION_ACTION_PREFIX,
    SPEC_RECOVERY_HORIZON_TURNS,
    SPEC_RESEARCH_ACTION_PREFIX,
    SPEC_RESOURCE_GROUPS,
    SPEC_VARIABLE_BY_CATEGORY,
    TURN_DURATION_MKS,
)
from .spec_lenses import (
    action_category,
    entity_type_of,
    frozen_variables,
    gate_opens,
)
from .spec_options import budget_deadlines

__all__ = [
    "act_target",
    "world_graph",
    "observation_context",
    "state_with_measured_dof",
    "calc_and_index",
    "recoverability",
    "SPEC_T_MEAS_MKS",
]

#: Момент замера, к которому привязано наблюдение (§3.3). `None` — наблюдение
#: взято в текущем ходе, отдельного замера не делалось.
SPEC_T_MEAS_MKS: Optional[float] = None

_TECH_TAIL = re.compile(r"_(\d+)$")


def act_target(name: str, actor_id: str) -> str:
    """Сущность, чья DoF меняется от акта.

    Акт меняет своего актора. Исследование ведёт игрок (`tech/cur_player`), и оно
    не поднимает его DoF — оно **сужает** его меню: выбранная дверь закрывается.
    Подъём приходится на тех, кому технология открывает дверь, и этот мост
    («технология → сущности, чьё меню она расширяет») ещё не построен. Пока его
    нет, акт не имеет права объявлять чужое восстановление — и не объявляет.
    """
    return actor_id


def world_graph(vectors: Mapping[str, Sequence[str]],
                fields_of: Mapping[str, Mapping[str, Any]],
                dof: Mapping[str, float],
                catalogue: Optional[Mapping[str, Any]] = None,
                known_techs: Iterable[str] = (),
                raw_menus: Optional[Mapping[str, Sequence[str]]] = None) -> WorldGraph:
    """Собрать граф мира: узлы — наблюдаемые сущности, акты — их живые векторы.

    `vectors` — меню по сущностям (векторы реакции, уже очищенные от мертвого),
    `fields_of` — наблюдаемые поля сущности, `dof` — измеренная DoF.

    Мост «технология → кому она открывает дверь» строится здесь: исследование
    ведёт **игрок**, а поднимает оно DoF **городов**, чей каталог пополняется
    открытым предметом. Поэтому акт исследования — не петля на себя, а ребро от
    игрока к городу: ровно такие рёбра и делает возможным вердикт о
    восстановлении (правило простоты пути запрещает `A → A`).

    `raw_menus` — меню до очистки: каталог города, по которому видно, что он
    **смог бы** строить, если бы дверь открылась.
    """
    nodes: dict[str, EntityNode] = {}
    acts: list[ActEdge] = []
    cities = {eid for eid in vectors if entity_type_of(eid) == "city"}
    for entity_id, names in vectors.items():
        kind = entity_type_of(entity_id)
        fields = fields_of.get(entity_id, {})
        frozen = set(frozen_variables(kind, fields))
        nodes[entity_id] = EntityNode(
            id=entity_id,
            observation="complete",           # своя сущность видна целиком (§3.5)
            current_dof=float(dof.get(entity_id, 0.0)),
        )
        for name in names:
            category = action_category(name)
            variable = SPEC_VARIABLE_BY_CATEGORY.get(category)
            if variable is not None and variable in frozen:
                continue                      # переменная мертва — акта нет
            if (catalogue is not None and kind == "player"
                    and name.startswith(SPEC_RESEARCH_ACTION_PREFIX)):
                acts.extend(_gate_acts(entity_id, name, catalogue, known_techs,
                                       cities, raw_menus or {}))
                continue
            target = act_target(name, entity_id)
            if target not in vectors:
                continue                      # цель не наблюдается — путь ведёт в пустоту
            effect = float(SPEC_ACT_EFFECT.get(category, 0.0))
            acts.append(ActEdge(
                id=f"{entity_id}:{name}",
                source=entity_id,
                target=target,
                category=category,
                requires=[],
                effect=({target: effect} if effect else {}),
                resources={},
                duration_mks=TURN_DURATION_MKS,
            ))
    means = sorted({str(r) for group in SPEC_RESOURCE_GROUPS for r in group})
    return WorldGraph(entities=nodes, means=means, acts=acts, exchanges=[])


def _gate_acts(player_id: str, action: str, catalogue: Mapping[str, Any],
               known_techs: Iterable[str], cities: Iterable[str],
               raw_menus: Mapping[str, Sequence[str]]) -> list[ActEdge]:
    """Рёбра исследования: по одному на город, которому этот акт открывает дверь.

    Ребро ведёт от игрока к городу и несёт прирост, равный числу предметов,
    которые город сможет строить **только** после этой технологии. Технология,
    которая не открывает ничего, что город мог бы построить, рёбер не даёт — и
    тогда пути восстановления через неё нет, как и должно быть.
    """
    tail = action.rsplit("_", 1)[-1]
    opened = gate_opens(tail, catalogue, known_techs)
    if not opened:
        return []
    out: list[ActEdge] = []
    for city_id in sorted(cities):
        buildable = {str(n[len(SPEC_PRODUCTION_ACTION_PREFIX):])
                     for n in raw_menus.get(city_id, [])
                     if str(n).startswith(SPEC_PRODUCTION_ACTION_PREFIX)}
        gain = len(set(opened) & buildable)
        if gain:
            out.append(ActEdge(
                id=f"{player_id}:{action}->{city_id}",
                source=player_id,
                target=city_id,
                category="research",
                requires=[],
                effect={city_id: float(gain)},
                resources={},
                duration_mks=TURN_DURATION_MKS,
            ))
    return out


def observation_context(world: WorldGraph, dof: Mapping[str, float]
                        ) -> ObservationContext:
    """Контекст наблюдения: `M(S)`, `T_rec(X)` по типам, горизонт счёта, отпечаток.

    `T_rec` выводится из **типа** сущности, а не из состояния: величина обязана
    быть одинаковой для всех гипотез одного цикла, иначе вердикты несовместимы.
    """
    t_rec: dict[str, float] = {}
    for entity_id in world.entities:
        turns = SPEC_RECOVERY_HORIZON_TURNS.get(entity_type_of(entity_id))
        if turns is not None:
            t_rec[entity_id] = float(turns) * TURN_DURATION_MKS
    means_class = list(SPEC_MEANS_CLASS)
    horizon = float(SPEC_COUNTING_HORIZON_TURNS) * TURN_DURATION_MKS
    return ObservationContext(
        world=world,
        means_class=means_class,
        t_rec=t_rec,
        counting_horizon_mks=horizon,
        observation_digest=world.observation_digest(means_class, t_rec, horizon),
        dof_override={str(k): float(v) for k, v in dof.items()},
    )


def state_with_measured_dof(state: Any, dof: Mapping[str, float],
                            deadlines: Optional[Mapping[str, float]] = None,
                            resources: Optional[Mapping[str, Any]] = None,
                            measurements: Optional[Mapping[str, Any]] = None):
    """Состояние §3.2 в том виде, в каком его читает **ядро**.

    DoF берётся из линз; `agency_index` и отметка источника коллапса — из матрицы
    прежней модели, если она эту сущность знала. Сущность, которой наблюдение не
    поддержало ни одного вектора реакции, в множество счёта не входит — иначе
    неполнота наблюдения читалась бы как доказательство (§4.9), — а игрок, которого
    прежняя модель не знала, заводится здесь: его ведёт собственное меню.

    Сроки сущностей объявлены, а не оставлены пустыми: `τ` — самый срочный из них
    (§3.2b), и пустой набор сроков означал бы «неизмерено», из-за чего §4.8b барёт
    каждый кандидат. Ставить `0.0` вместо объявления — выдумывать катастрофу.
    """
    deadlines = ({str(k): float(v) for k, v in deadlines.items()} if deadlines
                 else budget_deadlines(dof))
    old = getattr(state, "entities", {}) or {}
    entities: dict[str, EntityState] = {}
    for entity_id in sorted(dof):
        src = old.get(entity_id)
        entities[entity_id] = EntityState(
            entity_id=entity_id,
            is_autonomous=True,
            agency_index=float(getattr(src, "agency_index", 1.0)),
            current_dof=max(0.0, min(1.0, float(dof[entity_id]))),
            is_collapse_source=bool(getattr(src, "is_collapse_source", False)),
            dof_known=True,
            time_to_collapse_mks=float(deadlines.get(entity_id, 0.0)),
            measurement=((measurements or {}).get(entity_id)
                         or getattr(src, "measurement", None)),
        )
    return SystemStateMatrix(
        global_time_to_collapse_mks=min(deadlines.values()) if deadlines else 0.0,
        context_switch_cost=0.0,
        entities=entities,
        resources=dict(resources or {}),
        deadlines=dict(deadlines),
    )


def calc_and_index(state: Any, ctx: ObservationContext,
                   core: Optional[DOFCalculusCore] = None) -> tuple[set[str], float]:
    """§4.2: множество счёта `calc(S)` и индекс по нему (§4.1)."""
    core = core or DOFCalculusCore()
    members = core.calc_members(state, ctx)
    return members, core.calculate_system_dof(state, members, ctx)


def recoverability(state: Any, ctx: ObservationContext,
                   core: Optional[DOFCalculusCore] = None) -> dict[str, dict[str, Any]]:
    """§6.1: вердикт по каждой сущности — вместе со свидетелем и оговоркой о полноте."""
    core = core or DOFCalculusCore()
    return {eid: core.recoverability_row(eid, ctx) for eid in sorted(state.entities)}