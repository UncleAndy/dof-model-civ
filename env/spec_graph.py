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
from typing import Any, Mapping, Optional, Sequence

from brain.spec.calculus_core import DOFCalculusCore, ObservationContext
from brain.spec.world_graph import ActEdge, EntityNode, WorldGraph

from .config import (
    SPEC_ACT_EFFECT,
    SPEC_COUNTING_HORIZON_TURNS,
    SPEC_MEANS_CLASS,
    SPEC_RECOVERY_HORIZON_TURNS,
    SPEC_RESOURCE_GROUPS,
    SPEC_VARIABLE_BY_CATEGORY,
    TURN_DURATION_MKS,
)
from .entity_extractor import EntityState
from .spec_lenses import (
    action_category,
    entity_type_of,
    frozen_variables,
)

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
                dof: Mapping[str, float]) -> WorldGraph:
    """Собрать граф мира: узлы — наблюдаемые сущности, акты — их живые векторы.

    `vectors` — меню по сущностям (векторы реакции, уже очищенные от замороженного),
    `fields_of` — наблюдаемые поля сущности, `dof` — измеренная DoF.
    """
    nodes: dict[str, EntityNode] = {}
    acts: list[ActEdge] = []
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


def state_with_measured_dof(state: Any, dof: Mapping[str, float]):
    """Состояние, в котором DoF — **измеренная** линзами, а не прежняя модель.

    Набор сущностей урезается до измеренных: сущность, которой наблюдение не
    поддержало ни одного вектора реакции, в множестве счёта не участвует —
    иначе неполнота наблюдения читалась бы как доказательство (§4.9).
    """
    clone = copy.deepcopy(state)
    clone.entities = {eid: ent for eid, ent in clone.entities.items() if eid in dof}
    for entity_id in sorted(set(dof) - set(clone.entities)):
        # Сущность, которую наблюдение поддерживает через своё меню, но которой
        # нет в матрице предыдущей модели (игрок): заводим её здесь.
        clone.entities[entity_id] = EntityState(entity_id=entity_id)
    for entity_id, entity in clone.entities.items():
        entity.current_dof = max(0.0, min(1.0, float(dof[entity_id])))
        entity.dof_known = True
    return clone


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