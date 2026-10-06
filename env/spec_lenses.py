"""DOF-Core v0.11 §4.6 — отображение игровых величин в линзы ψ_var · ψ_opt · ψ_con.

ЧТО ЭТОТ МОДУЛЬ ДЕЛАЕТ И ЧЕГО НЕ ДЕЛАЕТ
---------------------------------------
Делает: добывает **счётчики** из игры — векторы реакции (`V`, `V_env`), требования
к ресурсам (`c_g`), средства (`C_g`), различаемые переменные (`F`, `F_env`).

Не делает: **не считает линзы сам**. `ψ_var`, `ψ_opt`, `ψ_con`, произведение,
дайджесты и весь §4.6/§4.7 живут в эталонном ядре (`brain/spec/measurement.py`),
вложенном в проект как `brain/spec` (DOF-Core v0.11, см. `brain/spec/__init__.py`).
Правило простое: **счётчики добывает мир, математику делает ядро**. Своя формула
здесь была бы второй линейкой — и любые числа стали бы несравнимы с эталоном.

Объявление (§3.4.1) — в `env/config.py`, блок `SPEC_*`. Оно хешируемое: меняете
значение там — меняется `ruler_digest`, и сравнение с прежними числами запрещено
(§3.4.4). Здесь — только процедуры, которые превращают наблюдение в счётчики.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from brain.spec.measurement import (
    LENS_ORDER,
    EntityMeasurement,
    LensObservation,
    MeasurementDeclaration,
    build_declaration,
    canonical_groups,
    derive_blocks,
    measure_entity,
)

from .config import (
    CONFIG,
    SPEC_COUNTING_HORIZON_TURNS,
    SPEC_ENERGY_UNIT,
    SPEC_GROUP_NUMERAIRE,
    SPEC_LENS_ORDER,
    SPEC_MANDATE_CAP,
    SPEC_OBSERVED_RATES,
    SPEC_PSI_ID,
    SPEC_REQUIREMENT_REDUCTION,
    SPEC_RESOURCE_GROUPS,
    SPEC_RESOURCE_UNITS,
    SPEC_RESPONSE_VECTOR_RULE,
    SPEC_V_ENV_SOURCES,
    SPEC_VARIABLE_SET_BY_TYPE,
)

#: Контроллеры, чьи действия адресованы сущности, которую экстрактор назвал
#: `<ctrl>_<actor>` (см. `env/entity_extractor.py`: `unit_<id>`, `city_<id>`,
#: `tech_<id>`). `gov` и `player` — системные: своей сущности у них нет.
ENTITY_CTRLS = ("unit", "city", "tech", "dipl")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Векторы реакции (V) — из настоящего меню мира
# ═══════════════════════════════════════════════════════════════════════════════

#: Контроллер CivRealm → префикс имени сущности. Дипломатия названа
#: `diplomacy_<id>`, а её контроллер — `dipl`, отсюда таблица, а не склейка строк.
_CTRL_PREFIX = {"unit": "unit", "city": "city", "dipl": "diplomacy"}

#: Технологический контроллер системный (`tech/cur_player`), но имя действия
#: называет саму технологию в хвосте: `research_tech_Alphabet_2` → технология 2
#: (проверено на живом наблюдении: `tech['2'].name == 'Alphabet'`). Поэтому
#: сущность берётся из имени действия, а не из актора.
_TECH_ACTION_PREFIXES = ("research_tech_", "set_tech_goal_")


def action_entity(ctrl_type: Any, actor_id: Any, action_name: Any) -> Optional[str]:
    """Сущность, которой адресовано действие, или None (действие системное)."""
    ctrl = str(ctrl_type)
    name = str(action_name)
    if ctrl in _CTRL_PREFIX:
        return f"{_CTRL_PREFIX[ctrl]}_{actor_id}"
    if ctrl == "tech" and name.startswith(_TECH_ACTION_PREFIXES):
        tail = name.rsplit("_", 1)[-1]
        if tail.isdigit():
            return f"tech_{tail}"
    return None


def _iter_actions(actions: Any) -> list[tuple[str, Any]]:
    """Действия актора в любой из форм, которые публикует мир.

    Наблюдены две: `{имя: params}` (так их отдаёт civrealm клиенту) и просто
    `[имя, ...]` (так они лежат в сохранённом наблюдении). Читать одну и падать на
    другой — значит мерить не мир, а формат сериализации.
    """
    if isinstance(actions, Mapping):
        return [(str(k), v) for k, v in actions.items()]
    if isinstance(actions, (list, tuple)):
        out: list[tuple[str, Any]] = []
        for item in actions:
            if isinstance(item, str):
                out.append((item, True))
            elif isinstance(item, (list, tuple)) and item:
                out.append((str(item[0]), item[1] if len(item) > 1 else True))
        return out
    return []


def menu_by_entity(available_actions: Mapping[str, Any],
                   valid_only: bool = True) -> dict[str, list[str]]:
    """Меню мира → {сущность: [имена действий]}.

    Формат CivRealm: `{ctrl_type: {actor_id: {action_name: params}}}`. Действие с
    пустыми параметрами мир не примет (civrealm срезает такие до предложения), и
    считать его вектором реакции значило бы объявить свободой то, чего нет.
    """
    menu: dict[str, list[str]] = {}
    for ctrl_type, actors in (available_actions or {}).items():
        if not isinstance(actors, Mapping):
            continue
        for actor_id, actions in actors.items():
            for action_name, params in _iter_actions(actions):
                if valid_only and not _truthy(params):
                    continue
                entity_id = action_entity(ctrl_type, actor_id, action_name)
                if entity_id is None:
                    continue
                menu.setdefault(entity_id, []).append(action_name)
    return menu


def _truthy(value: Any) -> bool:
    """Пустой словарь/список/None/массив — «мир это не предложит»."""
    if value is None:
        return False
    if isinstance(value, Mapping):
        return bool(value)
    try:
        return bool(value) and len(value) > 0
    except TypeError:
        return bool(value)


def response_vector_count(names: Iterable[str],
                          rule: str = SPEC_RESPONSE_VECTOR_RULE) -> int:
    """V — число различимых векторов реакции.

    `per_action_name`: каждое имя действия — свой вектор (`goto_0`…`goto_7` —
    восемь разных реакций). Правило объявлено в конфиге и входит в дайджест.
    """
    unique = {str(n) for n in names}
    if rule == "per_action_name":
        return len(unique)
    raise ValueError(f"неизвестное правило счёта векторов реакции: {rule!r}")


def disturbance_count(active_sources: Iterable[str],
                      declared: Sequence[str] = SPEC_V_ENV_SOURCES) -> int:
    """`V_env` — внешние возмущения, СНИМАЮЩИЕ вектор реакции (§4.6).

    Считаются только объявленные источники: счёт за разные списки — разные
    линейки. Источник, которого нет в объявлении, игнорируется молча НЕ здесь —
    он просто не входит в объявленный набор, а набор и есть объявление.
    """
    declared_set = set(declared)
    return len({str(s) for s in active_sources} & declared_set)


def active_disturbances(obs: Mapping[str, Any], entity_id: str, entity_type: str,
                        my_player_id: Optional[int] = None) -> list[str]:
    """Наблюдённые возмущения сущности — из объявленного набора источников (§4.6).

    Возмущение **снимает вектор реакции**: вражеский боевой юнит в радиусе
    «ход + удар» может уничтожить сущность, а с ней исчезают все её векторы.
    Заморозка размерности (лимит, закон, мандат) сюда НЕ входит — она в `F_env`.

    Источник, которого мир не публикует, не выдумывается: он просто не активен.
    Считаются только источники из объявления — иначе два счёта по разным спискам
    были бы несравнимы.
    """
    me_id = CONFIG.my_player_id if my_player_id is None else my_player_id
    hostile = [
        u for u in (obs.get("unit") or {}).values()
        if isinstance(u, Mapping) and u.get("owner") != me_id
    ]
    if not hostile:
        return []
    collection = obs.get("unit") if entity_type == "unit" else obs.get("city")
    rec = (collection or {}).get(str(entity_id).split("_", 1)[-1])
    if not isinstance(rec, Mapping) or "x" not in rec or "y" not in rec:
        return []
    x, y = float(rec.get("x") or 0.0), float(rec.get("y") or 0.0)
    reach = (float(rec.get("moves_left") or 0.0) + 1.0) if entity_type == "unit" else 3.0
    for u in hostile:
        if "x" in u and "y" in u:
            if max(abs(float(u["x"]) - x), abs(float(u["y"]) - y)) <= reach:
                return ["hostile_in_strike_range"]
    return []


def variety_counters(menu_names: Iterable[str],
                     active_disturbances: Iterable[str] = ()) -> dict[str, float]:
    """Пара счётчиков линзы разнообразия (§4.6). Целые счётчики, не доли."""
    return {
        "V": float(response_vector_count(menu_names)),
        "V_env": float(disturbance_count(active_disturbances)),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Требования → блоки (c_g, C_g)
# ═══════════════════════════════════════════════════════════════════════════════

def reduce_requirements(
    per_transition: Sequence[Mapping[str, float]],
    rule: str = SPEC_REQUIREMENT_REDUCTION,
) -> dict[str, float]:
    """Требования переходов → одно требование на ресурс (§4.6).

    Спека требует, чтобы `c_g` выводилось **именованной процедурой** из
    «per-resource requirements of the entity's transitions»; свёртка набора
    переходов в одно число — и есть эта процедура, поэтому она объявлена.

    `min` (принято): требование самого дешёвого доступного перехода — «хватает
    на что-то одно ⇒ канал открыт». `mean` — середина. `selected` — требование
    выбранного перехода (тогда линза читает кандидата, а не сущность).
    """
    resources = {str(r) for t in per_transition for r in t}
    out: dict[str, float] = {}
    for res in sorted(resources):
        amounts = [max(0.0, float(t.get(res, 0.0))) for t in per_transition]
        if not amounts:
            out[res] = 0.0
        elif rule == "min":
            out[res] = min(amounts)
        elif rule == "mean":
            out[res] = sum(amounts) / len(amounts)
        elif rule == "selected":
            raise ValueError(
                "правило 'selected' требует конкретного перехода: передайте "
                "per_transition из одного перехода"
            )
        else:
            raise ValueError(f"неизвестное правило свёртки требований: {rule!r}")
    return out


def option_blocks(requirements: Mapping[str, float],
                  means: Mapping[str, float],
                  groups: Sequence[Sequence[str]] = SPEC_RESOURCE_GROUPS,
                  rates: Mapping[tuple[str, str], float] = SPEC_OBSERVED_RATES,
                  cap: Optional[float] = SPEC_MANDATE_CAP
                  ) -> list[tuple[float, float]]:
    """Блоки `(c_g, C_g)` — **эталонной** процедурой `derive_blocks` (§4.6).

    Курсы `w_j` берутся из объявленных наблюдённых курсов в нумэрайр группы.
    Сейчас объявленный набор пуст — значит «курс не измерен», и эталон подставляет
    1.0. Это записано в объявлении, а не растворено в коде.
    """
    weights = _weights_to_numeraire(groups, rates)
    return derive_blocks(dict(requirements), dict(means), groups, weights, cap)


def _group_numeraire(group: Sequence[str]) -> Optional[str]:
    """Нумэрайр группы — по её членам, отсортированным как в объявлении."""
    return SPEC_GROUP_NUMERAIRE.get(",".join(sorted(str(m) for m in group)))


def _weights_to_numeraire(groups: Sequence[Sequence[str]],
                          rates: Mapping[tuple[str, str], float]
                          ) -> dict[str, float]:
    """`(ресурс, нумэрайр) → курс` в вид, который ждёт `derive_blocks`."""
    weights: dict[str, float] = {}
    for group in groups:
        members = [str(m) for m in group]
        numeraire = _group_numeraire(members)
        if numeraire is None:
            continue
        for member in members:
            rate = rates.get((member, numeraire))
            if rate is not None:
                weights[member] = float(rate)
    return weights


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Различаемые переменные (F) — и замороженный извне спрос (F_env)
# ═══════════════════════════════════════════════════════════════════════════════

def constraint_counters(variables: Sequence[str],
                        frozen: Sequence[str] = ()) -> dict[str, float]:
    """Пара счётчиков линзы ограничения (§4.6).

    `F` — сколько объявленных переменных **ещё не заморожено**;
    `F_env` — сколько заморожено **извне** (лимит правил, мандат, физический
    закон, унаследованное требование совместимости).

    Заморозка, которой нет в объявленном наборе, — ошибка входа, а не ноль:
    молча проигнорированная, она сделала бы `F` больше, чем есть переменных.
    """
    declared = {str(v) for v in variables}
    frozen_set = {str(v) for v in frozen}
    unknown = frozen_set - declared
    if unknown:
        raise ValueError(
            f"заморожены переменные вне объявленного набора {sorted(declared)}: "
            f"{sorted(unknown)}"
        )
    return {"F": float(len(declared - frozen_set)), "F_env": float(len(frozen_set))}


def entity_type_of(entity_id: str) -> str:
    """Тип сущности по имени, как их даёт экстрактор (`unit_113` → `unit`)."""
    return str(entity_id).split("_", 1)[0]


def frozen_variables(entity_type: str, fields: Mapping[str, Any]) -> list[str]:
    """Замороженные извне переменные сущности — по наблюдаемым полям.

    Заморозка — это **спрос извне**, а не решение агента (§4.6): ход, израсходованный
    правилами; производство, остановленное беспорядком; уже известная технология.
    Возмущения (враг, осада) сюда НЕ относятся: они снимают векторы реакции и живут
    в `V_env`. Спека прямо запрещает менять эти два места местами.
    """
    declared = SPEC_VARIABLE_SET_BY_TYPE.get(entity_type, ())
    frozen: list[str] = []
    if entity_type == "unit":
        # Правила дают юниту конечное число ходов: исчерпаны — позиция заморожена.
        if _num(fields.get("moves_left"), 0.0) <= 0.0:
            frozen.append("position")
    elif entity_type == "city":
        # Беспорядок останавливает производство — это то, что останавливает игра.
        if _num(fields.get("ppl_unhappy"), 0.0) > _num(fields.get("ppl_happy"), 0.0):
            frozen.append("production")
    elif entity_type == "tech":
        # Уже известная технология не исследуется: `inv_state` наблюдался как 1 у
        # известной (Alphabet) и 0 у неизвестной (Advanced Flight).
        if _num(fields.get("inv_state"), 0.0) >= 1.0:
            frozen.append("research")
    return [v for v in frozen if v in declared]


def constraint_observation(entity_type: str,
                           fields: Mapping[str, Any]) -> dict[str, float]:
    """Готовая пара `F`/`F_env` для сущности — объявленный набор + наблюдённая заморозка."""
    variables = SPEC_VARIABLE_SET_BY_TYPE.get(entity_type, ())
    return constraint_counters(variables, frozen_variables(entity_type, fields))


def _num(value: Any, default: float = 0.0) -> float:
    """CivRealm пропускает и обнуляет поля — читаем как число, не падая."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Сборка наблюдения и замер — эталонным ядром
# ═══════════════════════════════════════════════════════════════════════════════

def lens_observation(variety: Optional[Mapping[str, float]] = None,
                     requirements: Optional[Mapping[str, float]] = None,
                     constraint: Optional[Mapping[str, float]] = None
                     ) -> LensObservation:
    """Сырые входы линз одной сущности (§4.6).

    Линза, оставленная `None`, — **неизмеренная**: она не ноль и не идеал, и
    §4.7 начислит за неё `u(t)`. Это и есть механизм «незнание ≠ отсутствие
    возможностей».
    """
    return LensObservation(
        variety=dict(variety) if variety is not None else None,
        requirements=dict(requirements) if requirements is not None else None,
        constraint=dict(constraint) if constraint is not None else None,
    )


def measure(bindings: Mapping[str, LensObservation],
            means: Mapping[str, float],
            u_value: float = 0.5,
            groups: Sequence[Sequence[str]] = SPEC_RESOURCE_GROUPS,
            rates: Mapping[tuple[str, str], float] = SPEC_OBSERVED_RATES,
            cap: Optional[float] = SPEC_MANDATE_CAP
            ) -> dict[str, EntityMeasurement]:
    """Замер всех сущностей **эталонным** ядром (§4.6–§4.7).

    `u_value` — цена незнания для неизмеренной линзы; при `τ = null` это `u₀`
    (§4.7). Передаётся вызывающим явно, чтобы не прятать решение внутри.
    """
    weights = _weights_to_numeraire(groups, rates)
    return {
        eid: measure_entity(eid, obs, u_value, dict(means), groups, weights, cap)
        for eid, obs in bindings.items()
    }


def total_index(measurements: Mapping[str, EntityMeasurement]) -> float:
    """`TotalDoF_index(S) = Σ ln(DoF(e))` (§4.1) — **отрицательный** по построению.

    Величина читается **только порядком**: сравниваются состояния, а не модули.
    Отсечение по `calc(S)` (§4.2) здесь не делается — это следующий шаг.
    """
    return sum(m.contribution for m in measurements.values())


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Объявление линейки (§3.4.1) — хешируемое содержимое
# ═══════════════════════════════════════════════════════════════════════════════

def spec_layer() -> dict[str, Any]:
    """Объявленный ресурсный слой и процедуры — в форме, которую ждёт ядро."""
    return {
        "resources": [
            {"id": res, "unit": SPEC_RESOURCE_UNITS[res]}
            for res in sorted(SPEC_RESOURCE_UNITS)
        ],
        "groups": [list(g) for g in SPEC_RESOURCE_GROUPS],
        "rates": {
            f"{src}->{dst}": {"rate": float(rate)}
            for (src, dst), rate in sorted(SPEC_OBSERVED_RATES.items())
        },
        "mandate": {"cap": SPEC_MANDATE_CAP},
        "numeraire": _group_numeraire(SPEC_RESOURCE_GROUPS[0]),
        "procedures": {
            "variety": f"{SPEC_PSI_ID}:count_response_vectors",
            "options_blocks": f"{SPEC_PSI_ID}:derive_blocks",
            "constraint": f"{SPEC_PSI_ID}:count_variables",
            "counting_horizon_turns": f"{SPEC_PSI_ID}:{SPEC_COUNTING_HORIZON_TURNS}",
            "requirement_reduction": SPEC_REQUIREMENT_REDUCTION,
            "response_vector_rule": SPEC_RESPONSE_VECTOR_RULE,
        },
    }


def declaration(bindings: Mapping[str, LensObservation],
                means: Mapping[str, float],
                tau_mks: float) -> MeasurementDeclaration:
    """Собрать замороженное объявление состояния (§3.4.1) — эталонной сборкой."""
    layer = spec_layer()
    return build_declaration(
        psi_id=SPEC_PSI_ID,
        lens_observations=dict(bindings),
        tau_mks=tau_mks,
        procedures=layer["procedures"],
        resources=layer["resources"],
        groups=layer["groups"],
        rates=layer["rates"],
        mandate=layer["mandate"],
        numeraire=layer["numeraire"],
        weights=_weights_to_numeraire(SPEC_RESOURCE_GROUPS, SPEC_OBSERVED_RATES),
        mandate_cap=SPEC_MANDATE_CAP,
    )


__all__ = [
    "ENTITY_CTRLS",
    "action_entity",
    "menu_by_entity",
    "response_vector_count",
    "disturbance_count",
    "active_disturbances",
    "variety_counters",
    "reduce_requirements",
    "option_blocks",
    "constraint_counters",
    "entity_type_of",
    "frozen_variables",
    "constraint_observation",
    "lens_observation",
    "measure",
    "total_index",
    "spec_layer",
    "declaration",
]
