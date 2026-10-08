"""
Entity extractor: CivRealm game state → DOF SystemStateMatrix.

Implements DOF-SPEC v0.9.1 §3.2 data model:
- EntityState for city, unit, tech, diplomacy entity types
- SystemStateMatrix with psi declaration (SHA-256 digest)
- TotalDoF_index computation (Nash log-product)

The DoF value of every entity is computed in **options** — the DOF-Core toolkit
defines a degree of freedom as a count of independent options (>= 1). The
calibration (weights, references, ceilings) is the one approved on 2026-09-26 and
lives in :mod:`env.config`; its derivation and its measured limits are in
``drafts/DOF_CALIBRATION.md``.

Every game field read here was verified against a captured live observation
(``tests/fixtures/real_obs_01.json``) rather than taken from documentation:
units carry ``type_hp`` / ``type_attack_strength`` / ``type_move_rate`` /
``type_worker`` / ``type_converted_to`` / ``upkeep_*``, cities carry ``size`` /
``surplus_*`` / ``ppl_*`` / ``improvements`` / ``city_corruption``, and
technologies carry ``inv_state`` / ``reqs`` / ``sup_units`` / ``sup_improvements``
with the full parameter set of everything they unlock.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from pydantic import BaseModel, Field, field_validator

from .config import (
    CONFIG,
    EPSILON,
    TURN_DURATION_MKS,
    MAX_TURNS,
    DOF_SCALE,        # mirrors world_model['DOF_SCALE']: used for the score field
    CITY_CEIL,        # mirrors world_model['CITY_CEIL']
    TECH_BASE_OPTIONS,
    POPULATION_UNIT_TYPES,
    first_city_food_gate as _first_city_food_gate,
    UNIT_TYPICAL_MAX_HP,
    HEALTH_PERCENT_THRESHOLD,
    UNIT_MAX_HP_BY_TYPE,
    HEALTH_COLLAPSE_RATIO,
    TECH_DOF_REF,
    CARRIER_GOAL_RADIUS,   # радиус поиска цели для шага носителя (§10.38, V2)
    DiplomacyWeights,
)
from .world_model import Provenance, WorldModel, default_model
from .site_eval import (
    SiteEvaluation,
    WORKABLE_OFFSETS,
    counterfactual_growth_sink,
    counterfactual_growth_sink_per_turn,
    evaluate_site,
    hypothetical_city_obs,
    size_at_horizon,
    tile_output,
)
from . import site_outcomes
from . import spec_attack as _spec_attack
from . import spec_collapse_candidates as _spec_collapse_candidates
from . import switch_channel as _switch_channel
from .terrain_work import WORK_ACTION_EXTRA, tile_effect, tile_terrain_extras


# ═══════════════════════════════════════════════════════════════════════════════
# DOF-SPEC data models (§3)
# ═══════════════════════════════════════════════════════════════════════════════

class EntityState(BaseModel):
    """DOF-SPEC §3.1 — state of a single distinguishable entity."""
    entity_id: str
    is_autonomous: bool = True
    agency_index: float = Field(ge=0.0, le=1.0, default=0.5)
    current_dof: float = Field(ge=0.0, le=1.0, default=0.5)
    #: The authoritative DoF of this entity, in OPTIONS (>= 1 for a live entity).
    #: `current_dof` is the same quantity normalised by `dof_ceiling` into the
    #: DOF-SPEC's [0, 1] field range, for consumers that expect that contract.
    dof_options: float = 0.0
    #: Reference used to normalise `dof_options` (the ceiling of this entity's
    #: class). 0.0 when unknown, in which case `current_dof` is used as-is.
    dof_ceiling: float = 0.0
    is_collapse_source: bool = False
    dof_known: bool = True
    time_to_collapse_mks: float = Field(gt=0.0, default=1e15)

    @field_validator('agency_index', 'current_dof', mode='before')
    @classmethod
    def clamp_float(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @property
    def dof_count(self) -> float:
        """DoF as an option count, whatever way this entity was constructed."""
        if self.dof_options > 0.0:
            return self.dof_options
        return self.current_dof * DOF_SCALE


class ResourceObservation(BaseModel):
    """DOF-SPEC §3.2a — observable resource with metadata."""
    value: Optional[float] = None
    unit: str = ""
    scale: float = 1.0
    source: str = ""
    last_measured_at: float = 0.0
    aging_time: float = 1e9
    estimated: Optional[float] = None
    estimation_source: list[str] = Field(default_factory=list)


class ActionOption(BaseModel):
    """DOF-SPEC §3.3 — a candidate action with projected outcomes."""
    option_id: str
    description: str = ""
    projected_dof_delta: dict[str, float] = Field(default_factory=dict)
    projected_resource_delta: dict[str, dict[str, float]] = Field(default_factory=dict)
    requires: list[str] = Field(default_factory=list)
    discovers: list[str] = Field(default_factory=list)
    is_reversible: bool = True
    estimated_duration_mks: float = 0.0
    projected_tau_delta: float = 0.0


class BridgeCalibration(BaseModel):
    """Quantities the action bridge needs, derived from the state itself.

    These are not part of DOF-SPEC's data model; they exist so the bridge can
    project an action's DoF delta from **this state** instead of from a table of
    guesses. Every value is computed by the extractor from real observation
    fields, and every action that cannot be priced this way is reported as
    unmeasured (delta 0) rather than given a plausible-looking positive number.
    """
    #: Options a freshly founded city would have, under the empire's current
    #: food/economy conditions but with no improvements (what a new settlement
    #: actually has). Used for the founding delta, which is a difference in
    #: state, not a constant.
    new_city_options: float = 0.0
    #: unit entity id → options of a city founded **at that unit's own site**.
    #: `build_city` carries no coordinates: the city appears on the tile the unit
    #: stands on, so the choice of site is a choice of *where to walk*. Only
    #: sites that pass the minimum-quality gate appear here; the rest are listed
    #: in ``nonviable_carrier_sites`` and are excised rather than scored low.
    new_city_options_by_unit: dict[str, float] = Field(default_factory=dict)
    #: unit entity ids whose site failed the quality gate (one-day towns).
    nonviable_carrier_sites: list[str] = Field(default_factory=list)
    #: unit entity id → the site evaluation behind the two fields above, so a
    #: decision can be audited (food, gate, growth horizon, delay price).
    site_report: dict[str, dict[str, Any]] = Field(default_factory=dict)
    #: unit entity id → discounted option gain from walking to the best site
    #: within the unit's reach. This is what gives a settler a reason to MOVE:
    #: standing on barren land, founding is excised, so the only way to realise
    #: the population engine is to go where a city can actually grow.
    site_move_gain_by_unit: dict[str, float] = Field(default_factory=dict)
    #: unit entity id → the walk that gain refers to (current vs best value).
    site_move_report: dict[str, dict[str, Any]] = Field(default_factory=dict)
    #: unit entity id → {экстра работы: опции, которые она добавит городу}.
    #: Это канал «рабочий → DoF города»: работа меняет выход клетки, клетку
    #: обрабатывает город. Эффект берётся из ИЗМЕРЕННОЙ таблицы
    #: (`MEASURED_EXTRA_EFFECTS`), поэтому неизмеренная работа молчит (0), а не
    #: получает правдоподобное число.
    terrain_work_gain_by_unit: dict[str, dict[str, float]] = Field(default_factory=dict)
    #: unit entity id → {экстра: город, которому работа принесёт выгоду}.
    terrain_work_report: dict[str, dict[str, Any]] = Field(default_factory=dict)
    #: Снимок модели, чтобы цены читали модель, а не литералы (витрина вопросов
    #: и цена незнания берут отсюда `AXIOM4_PENALTY_OPTIONS`).
    model_values: dict[str, Any] = Field(default_factory=dict)
    #: Семейство действия → сколько раз агент уже пробовал действие с неизмеренным
    #: эффектом. Любопытство ограничено: после `CONFIDENCE_K` проб семейства
    #: надбавка за незнание равна нулю, и агент возвращается к полезным действиям.
    experiment_attempts: dict[str, int] = Field(default_factory=dict)
    #: Ключи, с которыми мир спорит (`pending`-доклады) — вопросы к эксперименту.
    contested_keys: list[dict[str, Any]] = Field(default_factory=list)
    #: Ключ → уверенность модели в нём (для надбавки за закрытие спора).
    confidence_by_key: dict[str, float] = Field(default_factory=dict)
    #: city entity id → option gain from one more standing improvement.
    improvement_gain: dict[str, float] = Field(default_factory=dict)
    #: unit rule name → options of one fresh unit of that type.
    unit_type_options: dict[str, float] = Field(default_factory=dict)
    #: improvement rule name → options one standing improvement adds.
    improvement_options: dict[str, float] = Field(default_factory=dict)
    #: tech entity id → option gain per turn of researching it.
    tech_research_gain: dict[str, float] = Field(default_factory=dict)


class SystemStateMatrix(BaseModel):
    """DOF-SPEC §3.2 — complete system state for a decision cycle."""
    psi: dict[str, str] = Field(default_factory=dict)
    global_time_to_collapse_mks: float = 1e15
    context_switch_cost: float = 0.0
    entities: dict[str, EntityState] = Field(default_factory=dict)
    resources: dict[str, ResourceObservation] = Field(default_factory=dict)
    #: System DoF sink in options (§7): the aggregate upkeep of all units alive.
    #: Kept as a separate quantity, not folded into any unit, because its bite
    #: depends on the treasury: irrelevant when rich, decisive when poor.
    dof_sink: float = 0.0
    #: Bridge-side, state-derived action pricing (see BridgeCalibration).
    bridge: BridgeCalibration = Field(default_factory=BridgeCalibration)


# ═══════════════════════════════════════════════════════════════════════════════
# Field readers (real CivRealm vocabulary)
# ═══════════════════════════════════════════════════════════════════════════════

def num(value: Any, default: float) -> float:
    """CivRealm omits or nulls fields (e.g. ``max_moves: null``)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def as_dict(value: Any) -> dict:
    """Observation containers as a dict.

    Never write `obs.get('unit') or {}` on a live observation: civrealm hands the
    nested containers over as **numpy arrays** in some code paths, and `array or
    {}` raises "truth value of an array with more than one element is ambiguous"
    instead of returning the array.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    tolist = getattr(value, 'tolist', None)
    if callable(tolist):
        value = tolist()
    if isinstance(value, dict):
        return value
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def as_list(value: Any) -> list:
    """Observation containers as a list (same numpy caveat as `as_dict`)."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    tolist = getattr(value, 'tolist', None)
    if callable(tolist):
        value = tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        return list(value)
    except TypeError:
        return [value]


def truthy(value: Any) -> bool:
    """Truth test that works on numpy scalars and arrays alike.

    `if params:` is used to decide whether civrealm will accept an action, and a
    numpy array there would raise instead of answering.

    Careful with numpy **scalars**: `np.False_` has `.size == 1`, so an earlier
    version returning `bool(size)` reported every numpy boolean as true. That
    silently counted every entry of a flag list as present (a city's
    `improvements` read as 68 of 68 instead of the real 21), saturating the city's
    first multiplier and erasing the difference between a developed and a bare
    city.
    """
    if value is None:
        return False
    shape = getattr(value, 'shape', None)
    if shape is not None:  # numpy scalar or array
        if len(shape) == 0:
            try:
                return bool(value)
            except (TypeError, ValueError):
                return False
        try:
            import numpy as _np

            return bool(_np.any(value))
        except Exception:  # pragma: no cover - numpy неожиданно недоступен
            return bool(getattr(value, 'size', 0))
    try:
        return bool(value)
    except (TypeError, ValueError):
        return False


def spec_field(spec: dict[str, Any], name: str, default: Any = None) -> Any:
    """Read a unit/improvement field under either naming convention.

    Live units prefix type properties (``type_hp``, ``type_move_rate``), while the
    unit specs carried inside a technology's ``sup_units`` do not (``hp``,
    ``move_rate``). Same quantity, two spellings — read both.
    """
    for key in (f"type_{name}", name):
        if key in spec and spec[key] is not None:
            return spec[key]
    return default


def health_ratio(unit_obs: dict[str, Any]) -> float:
    """Hit points → fraction of this unit type's own ceiling.

    CivRealm reports HIT POINTS whose ceiling differs per type (Settlers 20,
    Workers 10) and ships the ceiling as ``type_hp``. A unit *type* spec (as
    carried inside a technology's ``sup_units``) has no current health at all —
    it describes a fresh unit, so its ceiling is also its health. Values above
    ``HEALTH_PERCENT_THRESHOLD`` are percentages from older captures and
    synthetic fixtures.
    """
    # Ceiling: `type_hp` on a live unit, `hp` on a type spec.
    type_hp = num(spec_field(unit_obs, 'hp', 0.0), 0.0)
    utype = str(spec_field(unit_obs, 'rule_name', '') or '').strip().lower()
    if type_hp <= 0.0:
        type_hp = UNIT_MAX_HP_BY_TYPE.get(utype, UNIT_TYPICAL_MAX_HP)

    # Current health: a live unit reports it as `health`; a type spec is fresh.
    raw = num(unit_obs.get('health', type_hp), type_hp)
    if raw > type_hp * 1.5:
        # Above its type's ceiling by a wide margin, this can only be a
        # percentage of full health (older captures and synthetic fixtures use
        # health=100 for an unharmed unit while the type ceiling is 10 or 20).
        type_hp = HEALTH_PERCENT_THRESHOLD
    ratio = raw / max(type_hp, EPSILON)
    return max(0.0, min(1.0, ratio))


def is_population_carrier(unit_obs: dict[str, Any]) -> bool:
    """Population carriers found cities: identified by name or by ``pop_cost``."""
    utype = str(spec_field(unit_obs, 'rule_name', '') or '').strip().lower()
    pop_cost = num(spec_field(unit_obs, 'pop_cost', 0), 0)
    return utype in POPULATION_UNIT_TYPES or pop_cost > 0


def unit_options(unit_obs: dict[str, Any], age: int = 0,
                 model: Optional[WorldModel] = None) -> tuple[float, float, float]:
    """DoF of a unit in options, as (options, s_current, s_future).

    Works for a live unit observation and for the unit specs a technology carries
    in ``sup_units`` — both describe the same type with the same parameters.

    ``s_current`` is what the unit can do now; ``s_future`` what it can create or
    become. A population carrier is the case where the two diverge sharply, so
    its vitality is counted once, in the future term (see
    ``POP_CARRIER_COUNTS_HEALTH_IN_CURRENT``).
    """
    vals = (model or default_model()).values()
    carrier = is_population_carrier(unit_obs)
    hr = health_ratio(unit_obs)

    s_current = vals['UNIT_EXISTENCE_W']
    if not carrier or vals['POP_CARRIER_COUNTS_HEALTH_IN_CURRENT']:
        s_current += vals['UNIT_HEALTH_W'] * hr
    s_current += vals['UNIT_ATTACK_W'] * min(1.0, num(spec_field(unit_obs, 'attack_strength', 0), 0) / vals['UNIT_ATTACK_REF'])
    s_current += vals['UNIT_DEFENSE_W'] * min(1.0, num(spec_field(unit_obs, 'defense_strength', 0), 0) / vals['UNIT_DEFENSE_REF'])
    s_current += vals['UNIT_FIREPOWER_W'] * min(1.0, num(spec_field(unit_obs, 'firepower', 0), 0) / vals['UNIT_FIREPOWER_REF'])
    move_rate = spec_field(unit_obs, 'move_rate', None)
    if move_rate is None:
        # Synthetic fixtures and older captures name it `max_moves`.
        move_rate = unit_obs.get('max_moves', 0)
    s_current += vals['UNIT_MOVE_W'] * min(1.0, num(move_rate, 0) / vals['UNIT_MOVE_REF'])
    s_current += vals['UNIT_VISION_W'] * min(1.0, num(spec_field(unit_obs, 'vision_radius_sq', 0), 0) / vals['UNIT_VISION_REF'])
    s_current += vals['UNIT_VETERAN_W'] * min(1.0, num(spec_field(unit_obs, 'veteran', 0), 0) / vals['UNIT_VETERAN_REF'])
    s_current = min(vals['UNIT_CURRENT_CAP'], s_current)

    s_future = 0.0
    if carrier:
        s_future += vals['UNIT_FUTURE_SETTLE_W']
    if spec_field(unit_obs, 'worker', False):
        s_future += vals['UNIT_FUTURE_WORKER_W']
    converted_to = spec_field(unit_obs, 'converted_to', None)
    if converted_to not in (None, 0):
        convert_time = max(1.0, num(spec_field(unit_obs, 'convert_time', 1), 1))
        s_future += vals['UNIT_FUTURE_CONVERT_W'] / min(1.0, convert_time)
    transport_capacity = num(spec_field(unit_obs, 'transport_capacity', 0), 0)
    if transport_capacity > 0 or spec_field(unit_obs, 'can_transport', False):
        s_future += vals['UNIT_FUTURE_TRANSPORT_W']

    # Age decay applies to a carried population (fixed people, eroding), never to
    # a machine.
    decay = 1.0
    if carrier:
        decay = max(vals['CARRIER_DECAY_FLOOR'], 1.0 - vals['CARRIER_DECAY_PER_TURN'] * max(0, age))

    options = vals['DOF_SCALE'] * (s_current + vals['W_FUTURE_UNIT'] * s_future * hr * decay)
    return options, s_current, s_future


def improvement_options(spec: dict[str, Any],
                        model: Optional[WorldModel] = None) -> float:
    """DoF an improvement adds, in options.

    A standing improvement is a persistent option for the city that holds it: the
    same weight it carries inside the city's first multiplier, expressed as a
    count (1 baseline + its contribution).
    """
    vals = (model or default_model()).values()
    # One improvement is worth the weight it carries inside the city's first
    # factor, so the two can never drift apart.
    return 1.0 + vals['CITY_M1_IMPROV']


def city_options(city_obs: dict[str, Any], garrison: int = 0,
                 model: Optional[WorldModel] = None) -> float:
    """DoF of a city in options — the approved three-multiplier scheme (§8)."""
    vals = (model or default_model()).values()
    size = num(city_obs.get('size', city_obs.get('population', 1)), 1)

    # Factor 1 — people and infrastructure.
    surplus_food = num(city_obs.get('surplus_food', city_obs.get('food', 0)), 0)
    food_stock = num(city_obs.get('food_stock', 0), 0)
    granary = num(city_obs.get('granary_size', 0), 0)
    improvements = as_list(city_obs.get('improvements'))
    improvements_count = sum(1 for v in improvements if truthy(v))
    m1 = 1.0 + vals['CITY_M1_FOOD'] * max(0.0, surplus_food)
    if granary > 0:
        m1 += vals['CITY_M1_GRANARY'] * min(1.0, food_stock / granary)
    m1 += vals['CITY_M1_IMPROV'] * improvements_count
    m1 = min(vals['CITY_CAP_M1'], m1)

    # Factor 2 — the economy: what the city can turn options into.
    m2 = 1.0
    m2 += vals['CITY_M2_SHIELD'] * num(city_obs.get('surplus_shield', city_obs.get('production', 0)), 0)
    m2 += vals['CITY_M2_TRADE'] * num(city_obs.get('surplus_trade', 0), 0)
    m2 += vals['CITY_M2_GOLD'] * num(city_obs.get('surplus_gold', city_obs.get('gold', 0)), 0)
    m2 += vals['CITY_M2_SCIENCE'] * num(city_obs.get('science', 0), 0)
    m2 += vals['CITY_M2_LUXURY'] * num(city_obs.get('luxury', 0), 0)
    m2 = min(vals['CITY_CAP_M2'], m2)

    # Factor 3 — permanent losses.
    drains = (num(city_obs.get('city_corruption', 0), 0)
              + num(city_obs.get('city_waste', 0), 0)
              + num(city_obs.get('city_pollution', 0), 0))
    sink = max(0.0, 1.0 - vals['CITY_CORRUPTION_W'] * drains)

    # Happiness and disorder (§6): disorder gates production and trade, because
    # that is what the game stops; the city's people and infrastructure remain.
    happy = city_obs.get('ppl_happy')
    unhappy = city_obs.get('ppl_unhappy')
    angry = num(city_obs.get('ppl_angry', 0), 0)
    if happy is None and unhappy is None:
        # Legacy captures carry a single net `happiness` score (-1 = unhappy
        # city); reading it as a count of happy citizens would invert its sign.
        legacy = num(city_obs.get('happiness', 0), 0)
        happy, unhappy = max(0.0, legacy), max(0.0, -legacy)
    happy = num(happy, 0)
    unhappy = num(unhappy, 0)
    disorder = unhappy > happy
    happiness_factor = max(0.0, 1.0 + vals['CITY_HAPPY_W'] * happy
                           - vals['CITY_UNHAPPY_W'] * unhappy - vals['CITY_ANGRY_W'] * angry)

    garrison_factor = 1.0 + vals['GARRISON_W'] * max(0, garrison)

    base = vals['CITY_BASE'] + vals['CITY_POP'] * size
    if disorder:
        # "Only existence" (§6): no economy, no happiness, but the city is not a
        # collapsed entity — disorder is recoverable, and the game keeps its
        # people and its food. Zeroing the whole DoF here would make a merely
        # displeased city contribute ln(ε) ≈ -13.8 to the system index and
        # dominate every decision.
        options = base * m1 * sink
    else:
        options = base * m1 * m2 * sink * happiness_factor * garrison_factor
    return min(vals['CITY_CEIL'], max(0.0, options))


def player_record(obs: dict[str, Any], my_player_id: Any) -> dict[str, Any]:
    """Запись своего игрока: живьём ключи ЦЕЛЫЕ, в сохранённом наблюдении строки.

    Ловушка, стоившая прогонов: живое `obs['player']` ключуется числами (`0`, `1`,
    …), а `obs['city']` и `available_actions` — строками. Поиск по одному написанию
    молча возвращает пусто, и «нет данных» выглядит как свойство мира. Это ЕДИНСТВЕННОЕ
    место с таким правилом: остальные модули зовут эту функцию, а не повторяют поиск.
    """
    section = as_dict(obs.get('player'))
    for key in (my_player_id, str(my_player_id)):
        record = section.get(key)
        if isinstance(record, dict) and record:
            return record
    if len(section) == 1:
        only = next(iter(section.values()))
        if isinstance(only, dict):
            return only
    return {}


def tech_options(tech_obs: dict[str, Any], as_known: bool = False,
                 model: Optional[WorldModel] = None) -> float:
    """DoF of a technology in options (§5.1).

    A technology is a gate. While unknown it offers exactly one option — the
    possibility itself. Once known it is worth 1 + everything it unlocks, priced
    with the same unit and improvement formulas used everywhere else, so a
    technology that opens a Bomber and a Carrier is worth more than one that
    opens nothing.

    ``as_known`` prices a technology that is still unknown as if it had been
    researched, which is what the bridge needs to project the value of
    researching it.
    """
    vals = (model or default_model()).values()
    options = vals['TECH_BASE_OPTIONS']
    if not as_known and num(tech_obs.get('inv_state', 0), 0) <= 0.5:
        return options
    for spec in as_list(tech_obs.get('sup_units')):
        if isinstance(spec, dict):
            options += unit_options(spec)[0]
    for spec in as_list(tech_obs.get('sup_improvements')):
        if isinstance(spec, dict):
            options += improvement_options(spec)
    return options


# ═══════════════════════════════════════════════════════════════════════════════
# Entity extractor
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExtractionResult:
    """Result of extracting DOF state from a CivRealm observation."""
    state: SystemStateMatrix
    turn: int
    info: dict[str, Any]


class GameStateExtractor:
    """
    Converts CivRealm observations into a DOF SystemStateMatrix.

    Entity types: city (population + three multiplier factors), unit (current
    capability + future potential, survival-gated), tech (gate + what it
    unlocks), diplomacy (relationship and available agreements).
    """

    def __init__(
        self,
        diplomacy_weights: Optional[DiplomacyWeights] = None,
        my_player_id: int = 0,
        model: Optional[WorldModel] = None,
        **_legacy_weights: Any,
    ):
        self.diplomacy_weights = diplomacy_weights or DiplomacyWeights()
        self.my_player_id = my_player_id
        #: The agent's model of the world (priors + provenance + the refinement
        #: loop). Every formula reads its weights from here, so a value the world
        #: corrected actually changes the numbers the agent computes with.
        self.model = model or WorldModel.from_config()
        # First turn each entity id was observed. A population carrier's people
        # erode with age, which needs a per-entity clock; the extractor lives for
        # one match, so it can hold it.
        self._first_seen: dict[str, int] = {}
        #: Prediction of the next founded city's value, and how many own cities we
        #: saw last turn: when the count grows, the prediction meets the fact and
        #: becomes a (predicted, observed) pair — the world cannot publish our own
        #: coefficient, so the only route to refining it is such a pair.
        #: Прогнозы по каждому носителю (кто где стоит) — чтобы сопоставить
        #: прогноз именно с тем городом, который этот носитель основал, а не
        #: со «средним по империи».
        self._city_predictions: dict[str, float] = {}
        self._carrier_pos: dict[str, tuple[int, int]] = {}
        #: Прогноз выхода площадки по каналам для каждого носителя (еда/щиты/
        #: торговля) — сырьё для живой сверки «прогноз площадки ↔ факт города».
        self._carrier_site_pred: dict[str, dict[str, float]] = {}
        #: Города, за которыми следим для сверки площадки: id → запись.
        self._pending_sites: dict[str, dict[str, Any]] = {}
        self._sites_initialized: bool = False
        self._tracked_city_count: int = 0
        self._own_city_count: int = 0
        #: Наблюдение нападения (порт `v2:brain/v2/attack.py`): ведёт срезы между
        #: ходами и ставит метку «источник коллапса» — только по наблюдённому.
        self.attack_tracker = _spec_attack.AttackTracker(my_player_id=my_player_id)
        #: Наш номер игрока — нужен читателям, которые сравнивают владельцев (кандидаты §13.64).
        self.my_player_id = my_player_id
        #: Предыдущее СЫРОЕ наблюдение для сравнения срезов — то же правило, что у трекера
        #: (срез вместо наблюдения даёт «потерь не наблюдено» на видимом нападении).
        self._collapse_prev_obs: Optional[dict[str, Any]] = None
        #: Кандидаты «возможного источника коллапса» (§13.64, правило владельца): ОТДЕЛЬНЫЙ
        #: канал. Подтверждённую метку `is_collapse_source` не подменяет и в ядро не пишется:
        #: кандидат — подозрение с названной причиной, метка — только наблюдённое нападение.
        self.last_collapse_candidates: dict[str, Any] = {}
        #: Последнее событие наблюдения нападения и то, что помечено в этом ходу.
        self.last_attack_event: dict[str, Any] = {"attacked": False, "victims": [],
                                                  "attackers": [], "marked": [],
                                                  "reason": "наблюдений ещё не было"}
        self.marked_collapse_sources: list[str] = []
        #: Канал смены производства (`produce_switch` из `v2`, §10.102). Смену ЗАЯВЛЯЕТ
        #: раннер (`note_switch`), величину потери даёт мир (падение `shield_stock`
        #: между срезами). Незакрытые заявки ждут следующего среза — как `_pending_sites`.
        self._pending_switches: list[dict[str, Any]] = []
        self._last_shield_stock: dict[str, Any] = {}
        self.switch_rows: list[dict[str, Any]] = []
        #: Ход последнего извлечения: `note_switch` может прийти до первого `extract`.
        self._turn: int = 0

    # ── Public API ────────────────────────────────────────────────────────

    def extract(
        self,
        observations: dict[str, Any],
        info: dict[str, Any],
        turn: int,
    ) -> ExtractionResult:
        """Parse CivRealm observations into DOF state.

        Parameters
        ----------
        observations : dict
            Raw observation from CivRealm env.step() or env.reset().
            Keys: 'unit', 'city', 'tech', 'dipl', 'player', ...
        info : dict
            Info dict from CivRealm. Keys: 'turn', 'available_actions', ...
        turn : int
            Current turn number.
        """
        entities: dict[str, EntityState] = {}

        # ── Порог площадки для ПЕРВОГО города (§10.27) ──────────────────────
        # То же правило, что в прогнозе: пока у нас нет городов, порог годности
        # падает с ходом (`max(1.0, 6.0 − 0.4·(ход−1))`), для последующих городов
        # он остаётся 6.0. Одна формула на проект: без этого один путь основывал бы
        # город на бедном старте, а второй стоял бы вечно — и сравнение путей
        # мерило бы разные правила, а не разные политики.
        self._turn = int(turn or 0)
        try:
            self._no_cities = not any(
                int((rec or {}).get("owner", self.my_player_id)) == int(self.my_player_id)
                for rec in (observations.get("city") or {}).values()
                if isinstance(rec, dict))
        except (TypeError, ValueError):
            self._no_cities = True

        self._extract_units(observations, entities, turn)
        self._extract_cities(observations, entities, turn)
        self._extract_techs(observations, entities)
        self._extract_diplomacy(observations, entities)

        # ── Наблюдение нападения (порт `v2:brain/v2/attack.py`) ─────────────
        # Сравниваются два ПОЛНЫХ среза; метка «источник коллапса» ставится только
        # по наблюдённому нападению (видимый чужой на смежной клетке) и держится
        # весь срок прогноза. Нет видимого соседа — виновный не назначается.
        # Метка — ВХОД для ядра, а не параметр модели: гипотеза не может её менять.
        self.last_attack_event = self.attack_tracker.observe(observations, turn)
        self.marked_collapse_sources = self.attack_tracker.apply(entities, turn)

        # ── Кандидаты «возможного источника коллапса» (§13.64) ──────────────
        # Кто из чужих МОГ ударить: при бое двух сторон защитник — тот, кто стоит на
        # клетке своего игрока (при недоступности признака кандидатами идут оба воюющих);
        # плюс любой посторонний юнит на нашей территории или в открытых клетках.
        # Кандидат ≠ подтверждённая метка: метку ставит только наблюдённое нападение выше.
        fresh = _spec_collapse_candidates.observe_candidates(
            self._collapse_prev_obs, observations, self.my_player_id, turn)
        # Правило владельца (§13.64): кандидат держится, пока первичное нападение НЕ наблюдено.
        # Само правило живёт в модуле (`carry_candidates`) — здесь только его вызов с признаком
        # наблюдённого нападения, который известен извлекателю.
        attacked = bool((self.last_attack_event or {}).get("attacked"))
        fresh = _spec_collapse_candidates.carry_candidates(
            fresh, self.last_collapse_candidates, attacked)
        self.last_collapse_candidates = fresh
        self._collapse_prev_obs = observations

        # ── Канал смены производства (`produce_switch`, §10.102) ────────────
        # Заявки раннера закрываются ФАКТОМ мира: запас щитов до и после смены.
        # Падение щитов без заявки потерей не считается — щиты тратит и сама постройка.
        self._close_pending_switches(observations, turn)

        tau = self._compute_tau(turn)

        # Reality keeps its primacy: whatever the world said this turn about
        # something the model claims is reconciled here. Corrections apply to the
        # NEXT decision — never retroactively to the state just extracted — so a
        # match stays reproducible.
        self._reconcile_world_model(observations, turn)
        self._reconcile_ruleset(observations, turn)
        self._record_city_prediction(observations, turn)
        # Пространственная сверка: прогноз выхода площадки против фактического
        # выхода города. Может опровергнуть модель площадок — и это её работа.
        self._track_site_outcomes(observations, turn)

        state = SystemStateMatrix(
            psi=self._compute_psi(entities, turn),
            global_time_to_collapse_mks=tau,
            entities=entities,
            dof_sink=self._compute_system_sink(observations, turn),
            bridge=self._compute_bridge_calibration(observations),
        )

        return ExtractionResult(state=state, turn=turn, info=info)

    def note_choice(self, actor: Any, family: Any) -> None:
        """Сообщить извлекателю НАШЕ последнее исполненное действие.

        Нужно ровно для одного: если юнит исчез потому, что мы сами его потратили
        (`build_city` / `join_city` — мир публикует их как потребляющие юнита), это
        не нападение. Без вызова исчезновение читается как потеря от нападения —
        дефект, который в `v2` лечился тем же механизмом (`consumed` в `attack.py`).
        Вызывает тот, кто действие исполнил (раннер), — извлекатель его не знает.
        """
        self.attack_tracker.note_choice(actor, family)

    def note_switch(self, chosen: Any, city: Any = None,
                    current: Any = None) -> None:
        """Заявить смену производства: её знает только тот, кто вариант выбрал.

        Вызывается раннером ПОСЛЕ выбора и до следующего наблюдения: величина потери
        станет известна на следующем срезе (падение `shield_stock`), поэтому заявка
        ждёт его закрытия. Имя текущей постройки из наблюдения не восстанавливается
        (`production_value` — числовой id), поэтому и `current` называет раннер.
        """
        if chosen is None:
            return
        for key, stock in (self._last_shield_stock.items() if city is None
                           else [(str(city), self._last_shield_stock.get(str(city)))]):
            self._pending_switches.append({"city": key, "turn": self._turn,
                                           "chosen": str(chosen),
                                           "current": None if current is None else str(current),
                                           "stock_before": stock})

    def _close_pending_switches(self, obs: dict[str, Any], turn: int) -> None:
        """Закрыть заявки фактом мира и дописать строки канала."""
        city_sec = obs.get("city") if isinstance(obs.get("city"), dict) else {}
        stocks = {str(cid): rec.get("shield_stock") for cid, rec in city_sec.items()
                  if isinstance(rec, dict)}
        if self._pending_switches:
            closed: list[dict[str, Any]] = []
            for pending in self._pending_switches:
                after = stocks.get(pending["city"])
                row, _why = _switch_channel.observe(
                    turn=pending["turn"], city=pending["city"],
                    stock_before=pending["stock_before"], stock_after=after,
                    current=pending["current"], chosen=pending["chosen"])
                if row is not None:
                    closed.append(row)
            if closed:
                self.switch_rows.extend(closed)
                _switch_channel.record(closed)
            self._pending_switches = []
        self._last_shield_stock = stocks

    def switch_loss_shields(self) -> tuple[Optional[float], int, str]:
        """Измеренная потеря щитов при смене — вход для `switch_loss_for`.

        **Только строки текущего прогона.** Корпус на диске — для разборов, не для цены:
        иначе чужие прогоны молча двигали бы цену отказа в новом матче (в `v2` цена
        бралась ровно из наблюдений своей партии). Пока не измерено — `None` с причиной:
        цена отказа берётся нулём С ПРИЧИНОЙ, а не по догадке.
        """
        return _switch_channel.measured_loss(self.switch_rows)

    # ── Unit extraction ───────────────────────────────────────────────────

    def _extract_units(
        self,
        obs: dict[str, Any],
        entities: dict[str, EntityState],
        turn: int = 0,
    ) -> None:
        """Extract units as entities, in options.

        A unit's DoF is its *future* state space: what it can still do and what it
        can still become. Per-turn consumables (moves left this turn) are a
        renewable budget, never a loss of options — scoring them as DoF made every
        decision look like a permanent loss and forbade a DoF-maximising agent
        from acting at all.
        """
        for unit_id, unit_obs in as_dict(obs.get('unit')).items():
            if not isinstance(unit_obs, dict):
                continue
            entity_id = f"unit_{unit_id}"
            utype = spec_field(unit_obs, 'rule_name', 'unknown') or 'unknown'

            carrier = is_population_carrier(unit_obs)
            age = 0
            if carrier:
                first_seen = self._first_seen.setdefault(entity_id, turn)
                age = max(0, turn - first_seen)

            hr = health_ratio(unit_obs)
            options, _s_current, _s_future = unit_options(unit_obs, age=age,
                                                          model=self.model)
            # Владелец (§13.89): DoF сущности = базовый DoF × доля здоровья (hr).
            # При нулевом здоровье DoF ровно ноль — тогда удар может довести цель
            # до известного нуля и дать свидетеля §4.2.
            options = options * hr

            # Survival is a gate, not a bonus: a nearly destroyed unit has almost
            # no future state space however well equipped it is.
            ttc = (TURN_DURATION_MKS * 1 if hr <= HEALTH_COLLAPSE_RATIO
                   else TURN_DURATION_MKS * 100)

            entities[entity_id] = EntityState(
                entity_id=entity_id,
                is_autonomous=False,  # units follow orders
                agency_index=0.1,
                current_dof=min(1.0, options / DOF_SCALE),
                dof_options=max(EPSILON, options),
                dof_ceiling=DOF_SCALE,
                is_collapse_source=False,
                dof_known=True,
                time_to_collapse_mks=ttc,
            )

    # ── City extraction ───────────────────────────────────────────────────

    def _extract_cities(
        self,
        obs: dict[str, Any],
        entities: dict[str, EntityState],
        turn: int = 0,
    ) -> None:
        """Extract cities as entities, in options."""
        cities = as_dict(obs.get('city'))
        garrison_by_tile = self._garrison_counts(obs)

        for city_id, city_obs in cities.items():
            if not isinstance(city_obs, dict):
                continue
            entity_id = f"city_{city_id}"
            tile = (city_obs.get('x'), city_obs.get('y'))
            garrison = garrison_by_tile.get(tile, 0)

            options = city_options(city_obs, garrison=garrison, model=self.model)

            surplus_food = num(city_obs.get('surplus_food', city_obs.get('food', 0)), 0)
            if surplus_food < 0:
                stock = num(city_obs.get('food_stock', 0), 0)
                starve_turns = max(1, math.ceil(stock / abs(surplus_food)))
                ttc = starve_turns * TURN_DURATION_MKS
            else:
                ttc = TURN_DURATION_MKS * 1000

            entities[entity_id] = EntityState(
                entity_id=entity_id,
                is_autonomous=True,
                agency_index=0.8,
                current_dof=min(1.0, options / CITY_CEIL),
                dof_options=max(EPSILON, options),
                dof_ceiling=CITY_CEIL,
                is_collapse_source=False,
                dof_known=True,
                time_to_collapse_mks=ttc,
            )

    def _garrison_counts(self, obs: dict[str, Any]) -> dict[tuple, int]:
        """Own units per tile: a garrison is how warriors protect a city's DoF."""
        counts: dict[tuple, int] = {}
        for unit_obs in as_dict(obs.get('unit')).values():
            if not isinstance(unit_obs, dict):
                continue
            if num(unit_obs.get('owner', self.my_player_id), self.my_player_id) != self.my_player_id:
                continue
            tile = (unit_obs.get('x'), unit_obs.get('y'))
            counts[tile] = counts.get(tile, 0) + 1
        return counts

    # ── Technology extraction ─────────────────────────────────────────────

    def _extract_techs(
        self,
        obs: dict[str, Any],
        entities: dict[str, EntityState],
    ) -> None:
        """Extract technologies as entities, in options.

        The technology domain is the largest in the system (87 of 95 entities in
        a start state) and, before this calibration, contributed exactly nothing:
        a research action measured Δindex = 0.0000. Modelling a technology as a
        gate — 1 option while unknown, 1 + everything it unlocks once known —
        makes that contribution measurable and attributes it to the technology
        entity the action acts upon.
        """
        for tech_id, tech_obs in as_dict(obs.get('tech')).items():
            if not isinstance(tech_obs, dict):
                continue
            entity_id = f"tech_{tech_id}"
            options = tech_options(tech_obs, model=self.model)

            entities[entity_id] = EntityState(
                entity_id=entity_id,
                is_autonomous=False,  # researched by the player, not by itself
                agency_index=0.2,
                current_dof=min(1.0, options / TECH_DOF_REF),
                dof_options=max(EPSILON, options),
                dof_ceiling=TECH_DOF_REF,
                is_collapse_source=False,
                dof_known=True,
                time_to_collapse_mks=1e15,
            )

    # ── Diplomacy extraction ──────────────────────────────────────────────

    def _extract_diplomacy(
        self,
        obs: dict[str, Any],
        entities: dict[str, EntityState],
    ) -> None:
        """Extract diplomatic relations as entities."""
        # CivRealm uses the 'dipl' key, not 'diplomacy'.
        dipl = as_dict(obs.get('dipl') if obs.get('dipl') is not None
                       else obs.get('diplomacy'))

        for player_id, dipl_obs in dipl.items():
            if str(player_id) == str(self.my_player_id):
                continue  # skip self
            if not isinstance(dipl_obs, dict):
                continue
            entity_id = f"diplomacy_{player_id}"

            # relationship: -1 war .. 0 neutral .. 1 allied; the live observation
            # carries `diplomatic_state` and a clause map instead of a score.
            rel = dipl_obs.get('relationship')
            if rel is None:
                state = num(dipl_obs.get('diplomatic_state', 0), 0)
                rel = min(1.0, max(-1.0, (state - 5) / 5.0))
            rel_ratio = (num(rel, 0) + 1.0) / 2.0

            alliance_ratio = min(1.0, len(as_list(dipl_obs.get('alliance_options'))) / 3.0)
            trade_ratio = min(1.0, len(as_list(dipl_obs.get('trade_options'))) / 3.0)

            dof = (self.diplomacy_weights.relationship * rel_ratio
                   + self.diplomacy_weights.alliance_options * alliance_ratio
                   + self.diplomacy_weights.trade_options * trade_ratio)

            entities[entity_id] = EntityState(
                entity_id=entity_id,
                is_autonomous=True,
                agency_index=0.6,
                current_dof=max(EPSILON, min(1.0, dof)),
                dof_options=max(EPSILON, dof * DOF_SCALE),
                dof_ceiling=DOF_SCALE,
                is_collapse_source=False,
                dof_known=True,
                time_to_collapse_mks=1e15,
            )

    # ── System sink ───────────────────────────────────────────────────────

    def _record_city_prediction(self, obs: dict[str, Any], turn: int) -> None:
        """Прогноз города против факта: единственный источник уточнения.

        Мир не публикует коэффициент ценности нового города — он публикует сам
        город. Поэтому, как только наших городов стало больше, чем в прошлом
        ходу, прогноз (сделанный по площадке) встречается с фактом и уходит в
        статистику (`record_pair`). Пары только накапливаются: молча подменять
        коэффициент по одному наблюдению — то же самое, что выдумывать числа.
        """
        own = [
            c for c in as_dict(obs.get('city')).values()
            if isinstance(c, dict)
            and num(c.get('owner', self.my_player_id), self.my_player_id) == self.my_player_id
        ]
        if len(own) > self._own_city_count and self._city_predictions:
            newest = max(own, key=lambda c: num(c.get('id', 0), 0))
            # Прогноз берём у носителя, который стоял НА клетке нового города:
            # именно его площадку мы оценивали. Если такого нет (носитель ушёл
            # или город основан иначе) — падаем на максимум прогнозов: это
            # грубее, зато не выдумывает связь, которой не видели.
            here = None
            for unit_id, pos in self._carrier_pos.items():
                if pos == (int(num(newest.get('x', -1), -1)),
                           int(num(newest.get('y', -1), -1))):
                    here = unit_id
                    break
            predicted = (self._city_predictions.get(here) if here is not None
                         else max(self._city_predictions.values()))
            observed = city_options(newest, garrison=0, model=self.model)
            self.model.record_pair('new_city_options', predicted,
                                   observed, turn=turn)
            self._city_predictions.clear()
            self._carrier_pos.clear()
        self._own_city_count = len(own)

    # ── Пространственная сверка: прогноз площадки ↔ факт города ───────────

    def _track_site_outcomes(self, obs: dict[str, Any], turn: int) -> None:
        """Сверить прогноз площадки с фактическим выходом города.

        Зачем это отдельно от пар «прогноз↔факт». Пары сравнивают наш же
        коэффициент с нашей же оценкой города — это внутренняя согласованность.
        Здесь сравнивается **прогноз модели с тем, что мир публикует сам**
        (`prod_food`, `prod_shield`, `prod_trade`), на одном городе, одном
        размере и одном месте. Это единственная проверка, которая может
        опровергнуть модель площадок, а не подтвердить её.

        Города не проверяются сразу: свежему городу ещё нечего показывать
        (работает 1-2 клетки), поэтому сверка откладывается на
        `OUTCOME_AGE_TURNS` ходов.
        """
        if not self._sites_initialized:
            for city in self._own_cities(obs):
                self._remember_site(city, turn, cause='start')
            self._sites_initialized = True
        elif len(self._own_cities(obs)) > self._tracked_city_count:
            newest = max(self._own_cities(obs),
                         key=lambda c: num(c.get('id', 0), 0))
            # 'appeared', а не 'founded': город мог быть основан ранее, а здесь
            # впервые прийти пакетом — называть его основанным значит утверждать
            # больше, чем мы видели.
            self._remember_site(newest, turn, cause='appeared')
        self._tracked_city_count = len(self._own_cities(obs))
        self._emit_site_outcomes(obs, turn)

    def _own_cities(self, obs: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            c for c in as_dict(obs.get('city')).values()
            if isinstance(c, dict)
            and num(c.get('owner', self.my_player_id), self.my_player_id)
            == self.my_player_id
        ]

    def _remember_site(self, city: dict[str, Any], turn: int,
                       cause: str) -> None:
        city_id = str(int(num(city.get('id', -1), -1)))
        if city_id in self._pending_sites or city_id.startswith('-1'):
            return
        x = int(num(city.get('x', -1), -1))
        y = int(num(city.get('y', -1), -1))
        entry: dict[str, Any] = {
            'city_id': city_id, 'turn': int(turn), 'cause': cause,
            'x': x, 'y': y,
            'size_at_start': int(num(city.get('size', 1), 1)),
        }
        # Прогноз площадки берём у носителя, стоявшего на клетке города: именно
        # его площадку оценивали перед основанием.
        for unit_id, pos in self._carrier_pos.items():
            if pos == (x, y) and unit_id in self._carrier_site_pred:
                entry['pred_at_founding'] = dict(self._carrier_site_pred[unit_id])
                break
        self._pending_sites[city_id] = entry

    def _emit_site_outcomes(self, obs: dict[str, Any], turn: int) -> None:
        if not self._pending_sites:
            return
        map_obs = as_dict(obs.get('map')) or {}
        cities = as_dict(obs.get('city')) or {}
        # Индекс по ИДЕНТИФИКАТОРУ, а не по ключу словаря. Это не придирка:
        # в живом наблюдении ключи `obs['city']` — целые числа (121), а в
        # JSON-фикстуре те же ключи становятся строками ("121"). Поиск по строке
        # находил ноль городов, и все 30 подряд записались как «потерянные»,
        # хотя на самом деле их просто искали не тем ключом. Индекс по id
        # устраняет зависимость от типа ключа вообще.
        by_id: dict[int, dict[str, Any]] = {}
        for value in cities.values():
            if isinstance(value, dict):
                found = int(num(value.get('id', -1), -1))
                if found >= 0:
                    by_id[found] = value
        vals = self.model.values()
        rows: list[dict[str, Any]] = []
        for city_id, entry in list(self._pending_sites.items()):
            age = int(turn) - int(entry['turn'])
            if age < site_outcomes.OUTCOME_AGE_TURNS:
                continue
            city = by_id.get(int(city_id)) if str(city_id).lstrip('-').isdigit() else None
            if not isinstance(city, dict):
                # Города нет в ЭТОМ наблюдении — но это не значит, что он потерян:
                # слой городов приходит пакетами (по изменению), а не каждый ход.
                # Первый промах записывать как «город исчез» — выдумывать факт.
                # Поэтому даём несколько попыток и только потом фиксируем потерю.
                missed = int(entry.get('misses', 0)) + 1
                entry['misses'] = missed
                if age < site_outcomes.LOST_AFTER_TURNS:
                    continue
                rows.append({'turn': int(turn), 'city_id': city_id, 'age': age,
                             'cause': entry['cause'], 'lost': True,
                             'misses': missed,
                             'x': entry['x'], 'y': entry['y'],
                             'available_city_ids': sorted(by_id)[:8]})
                del self._pending_sites[city_id]
                continue
            size = int(num(city.get('size', 1), 1))
            row: dict[str, Any] = {
                'turn': int(turn), 'city_id': city_id, 'age': age,
                'cause': entry['cause'], 'x': entry['x'], 'y': entry['y'],
                'size': size, 'lost': False,
                'obs_food': float(num(city.get('prod_food', 0), 0)),
                'obs_shield': float(num(city.get('prod_shield', 0), 0)),
                'obs_trade': float(num(city.get('prod_trade', 0), 0)),
                # Модель предсказывает ВАЛОВОЙ выход площадки, а мир публикует
                # ЧИСТЫЙ (уже за вычетом отходов и коррупции). Без этих полей
                # сравнение получается неравным: торговля «не сходится» в 3,5
                # раза просто потому, что её съедает коррупция, которую модель
                # не вычитает. Храним потери, чтобы сравнивать и так, и так.
                'obs_waste': float(num(city.get('city_waste', 0), 0)),
                'obs_corruption': float(num(city.get('city_corruption', 0), 0)),
                'obs_pollution': float(num(city.get('city_pollution', 0), 0)),
                # Недовольные жители в Freeciv НЕ работают на клетках. Модель же
                # считает площадку как «работают все size+1 клеток», поэтому при
                # недовольстве прогноз обязан быть выше факта. Эти поля нужны,
                # чтобы отличить эту причину от простой ошибки модели.
                'obs_unhappy': float(num(city.get('ppl_unhappy', 0), 0)),
                'obs_angry': float(num(city.get('ppl_angry', 0), 0)),
                'obs_content': float(num(city.get('ppl_content', 0), 0)),
                'obs_happy': float(num(city.get('ppl_happy', 0), 0)),
                'pred_food': None, 'pred_shield': None, 'pred_trade': None,
            }
            try:
                site = evaluate_site(map_obs, int(entry['x']), int(entry['y']),
                                     size=max(1, size), vals=vals)
                row['pred_food'] = float(site.food)
                row['pred_shield'] = float(site.shields)
                row['pred_trade'] = float(site.trade)
                row['site_viable'] = bool(site.viable)
            except Exception:  # noqa: BLE001 - сверка не критична для матча
                row['site_viable'] = None
            row['pred_at_founding'] = entry.get('pred_at_founding')
            # Сырьё для разбора ПРАВИЛА назначения жителей: все 21 клетки
            # площадки (центр первым) и признак «разведана». Без этого нельзя
            # ответить, почему щиты и торговля не сходятся: неизвестно, какие
            # именно клетки игра обрабатывала. Хранится, чтобы вопрос решался по
            # уже собранным данным, а не новыми догадками.
            try:
                coords = [(int(entry['x']), int(entry['y']))] + [
                    (int(entry['x']) + dx, int(entry['y']) + dy)
                    for dx, dy in WORKABLE_OFFSETS]
                tiles: list[list[float]] = []
                known_flags: list[int] = []
                for tx, ty in coords:
                    tf, ts, tt, is_known = tile_output(map_obs, tx, ty)
                    tiles.append([float(tf), float(ts), float(tt)])
                    known_flags.append(1 if is_known else 0)
                row['tiles'] = tiles
                row['tiles_known'] = known_flags
            except Exception:  # noqa: BLE001 - сверка не критична для матча
                pass
            rows.append(row)
            del self._pending_sites[city_id]
        if rows:
            site_outcomes.record(rows)

    def _upkeep_prices(self, obs: dict[str, Any]) -> dict[str, float] | None:
        """Цена одного пункта содержания в опциях — из формулы ГОРОДА (§10.35, V3-1).

        Правило проекта: параметр берётся из мира. Плоский вес 0.05 переводил пункт
        содержания в опции почти по нулю, хотя сам город оценивает +1 золота в
        **+0.570** опций, +1 щита — в +0.285, +1 еды — в +0.969 (замер на реальной
        записи города). Здесь те же числа считаются ЖИВО по записи нашего города:
        берётся разность `city_options` при сдвиге поля на +1. Если города в
        наблюдении нет — возвращается `None`, и работает запасной плоский вес.
        """
        from env.config import UPKEEP_PRICE_FOOD, UPKEEP_PRICE_GOLD, UPKEEP_PRICE_SHIELD
        fallback = {"food": UPKEEP_PRICE_FOOD, "gold": UPKEEP_PRICE_GOLD,
                    "shield": UPKEEP_PRICE_SHIELD}
        try:
            from env.entity_extractor import city_options
        except Exception:  # noqa: BLE001
            return None
        model = getattr(self, "model", None)
        collected: dict[str, list[float]] = {"food": [], "gold": [], "shield": []}
        for rec in as_dict(obs.get("city")).values():
            if not isinstance(rec, dict):
                continue
            owner = rec.get("owner")
            if owner is not None and num(owner, -1) != self.my_player_id:
                continue
            try:
                base = float(city_options(rec, model=model))
            except Exception:  # noqa: BLE001
                continue
            for field, key in (("surplus_gold", "gold"), ("surplus_shield", "shield"),
                               ("surplus_food", "food")):
                if rec.get(field) is None:
                    continue
                shifted = dict(rec)
                try:
                    shifted[field] = float(rec[field]) + 1.0
                    collected[key].append(float(city_options(shifted, model=model)) - base)
                except Exception:  # noqa: BLE001
                    continue
        prices = {k: (sum(v) / len(v) if v else fallback[k])
                  for k, v in collected.items()}
        if not any(v for v in collected.values()):
            return None                 # города не было — живую цену взять неоткуда
        return prices

    def _compute_system_sink(self, obs: dict[str, Any], turn: int) -> float:
        """System-level DoF sinks (§7), in options.

        Two parts, both belonging to the system rather than to any single entity,
        because how much they bite depends on the treasury that pays them:

        * **unit upkeep** — summed over all units, weighted by
          ``UNIT_UPKEEP_SINK_W``;
        * **undeployed population** — every turn a population carrier has existed
          without founding a city is a turn the empire does not get its
          population engine. This one accumulates without saturation (unlike the
          carrier's decay, which is a proxy for the price of time and stops at
          its floor), so delay is punished monotonically and irreversibly.

        The delay part is now the **counterfactual growth** of factor (б)
        (approved 2026-09-26): the site around the carrier is evaluated by tile
        (``env.site_eval``) and the per-turn cost is the DoF a city founded here
        would have gained this turn — ``W_GROWTH × CITY_POP × DOF_SCALE ×
        surplus / granary(size)``. A site that fails the minimum-quality gate
        contributes no growth, so its cost falls back to the flat floor: a
        one-day town is forbidden, not merely expensive (doc §3).
        """
        vals = self._site_vals()
        # Еда на жителя — из правил стенда, а не из литерала.
        if 'rules.food_cost' in vals:
            vals['FOOD_COST'] = vals['rules.food_cost']
        map_obs = as_dict(obs.get('map'))
        capital = not any(
            isinstance(c, dict)
            and num(c.get('owner', self.my_player_id), self.my_player_id) == self.my_player_id
            for c in as_dict(obs.get('city')).values()
        )
        upkeep = 0.0
        upkeep_by_field = {"food": 0.0, "gold": 0.0, "shield": 0.0}
        delay_sink = 0.0
        for unit_id, unit_obs in as_dict(obs.get('unit')).items():
            if not isinstance(unit_obs, dict):
                continue
            # Содержание и задержку считаем ТОЛЬКО по своим юнитам: чужие — не наш
            # сток (найдено §10.35: сток суммировал содержание всех записей
            # наблюдения, а записи включают чужие юниты). Юнит без поля владельца
            # считается своим — иначе пострадали бы синтетические наблюдения.
            owner = unit_obs.get('owner')
            if owner is not None and num(owner, -1) != self.my_player_id:
                continue
            upkeep_by_field["food"] += num(unit_obs.get('upkeep_food', 0), 0)
            upkeep_by_field["gold"] += num(unit_obs.get('upkeep_gold', 0), 0)
            upkeep_by_field["shield"] += num(unit_obs.get('upkeep_shield', 0), 0)
            upkeep += (num(unit_obs.get('upkeep_food', 0), 0)
                       + num(unit_obs.get('upkeep_gold', 0), 0)
                       + num(unit_obs.get('upkeep_shield', 0), 0))
            if not is_population_carrier(unit_obs):
                continue
            first_seen = self._first_seen.setdefault(f"unit_{unit_id}", turn)
            age = max(0, turn - first_seen)
            if age == 0:
                continue
            site = self._carrier_site(unit_obs, map_obs, vals)
            # Цена задержки — по ФОРМУЛЕ ГОРОДА (пункт 3): рост считается тем же
            # кодом, что и настоящий город, поэтому множители площадки (еда,
            # щиты, торговля, бесплатный Palace столицы) влияют на неё, а не
            # подменяются плоским «житель = CITY_POP × DOF_SCALE».
            rate = self._carrier_rate(site, capital)
            delay_sink += rate * age
        # Цена содержания: ЖИВАЯ (по формуле города, §10.35 V3-1), а не плоский вес —
        # плоский вес 0.05 переводил пункт содержания в опции почти по нулю, хотя сам
        # город оценивает золото в 0.570 опций, щит — в 0.285, еду — в 0.969.
        from env.config import UPKEEP_PRICE_LIVE
        prices = self._upkeep_prices(obs) if UPKEEP_PRICE_LIVE else None
        if prices is None:
            upkeep_cost = vals['UNIT_UPKEEP_SINK_W'] * upkeep
        else:
            upkeep_cost = (upkeep_by_field["gold"] * prices["gold"]
                           + upkeep_by_field["shield"] * prices["shield"]
                           + upkeep_by_field["food"] * prices["food"])
        # Части стока и цены — для прибора: печатать их «по старому весу» нельзя, иначе
        # отчёт расходится с тем, что модель реально вычитает (измерено: прибор показывал
        # 0.35, а сток вырос до 5.28 — расхождение и было признаком ошибки прибора).
        self._last_sink_parts = {
            "upkeep": upkeep_cost, "delay": delay_sink, "prices": prices,
            "upkeep_points": dict(upkeep_by_field),
            "flat_weight": vals['UNIT_UPKEEP_SINK_W'] * upkeep,
        }
        return upkeep_cost + delay_sink

    def _carrier_rate(self, site, capital: bool) -> float:
        """Цена ОДНОГО хода простоя носителя на площадке, в опциях (§7, §10.38).

        Одна и та же величина служит двум целям: стоку «задержка населения» (сколько
        система теряет за каждый ход без города) и цене ШАГА к площадке (§10.38, V2):
        шаг несёт `rate / N`, поэтому весь путь до площадки возвращает ровно `rate`.
        """
        vals = self._site_vals()
        if 'rules.food_cost' in vals:
            vals['FOOD_COST'] = vals['rules.food_cost']
        value_of_size = (
            (lambda s, _site=site: self._site_city_value_at(_site, capital, s))
            if site is not None else (lambda s: 0.0)
        )
        return float(counterfactual_growth_sink(site, vals, value_of_size, size=1))

    def carrier_walk_goal(self, obs: dict[str, Any], unit_id: str
                          ) -> Optional[tuple[tuple[int, int], float]]:
        """Ближайшая годная площадка вокруг носителя и цена простоя НА НЕЙ (§10.38).

        Нужно прогнозу, чтобы дать шагу к цели ненулевую дельту: цена простоя делится
        на число шагов до этой площадки, поэтому весь путь возвращает ровно её.
        Возвращает ``((x, y), rate)`` или ``None``, если носителя нет, он вне карты
        или годной площадки в объявленном радиусе нет — тогда шаг остаётся без цели
        (и с нулевой дельтой: «ходить без причины» правило не разрешает).

        Результат кэшируется на (ход, юнит): обход окна стоит вызовов оценки площадки,
        а внутри одного хода он не меняется.
        """
        cache = getattr(self, "_goal_cache", None)
        if cache is None:
            cache = self._goal_cache = {}
        cache_key = (getattr(self, "_turn", None), str(unit_id))
        if cache_key in cache:
            return cache[cache_key]
        result: Optional[tuple[tuple[int, int], float]] = None
        try:
            unit_obs = as_dict(obs.get('unit')).get(unit_id)
            if unit_obs is None:
                unit_obs = as_dict(obs.get('unit')).get(str(unit_id))
            map_obs = as_dict(obs.get('map'))
            if isinstance(unit_obs, dict) and map_obs and is_population_carrier(unit_obs):
                x, y = unit_obs.get('x'), unit_obs.get('y')
                if x is not None and y is not None:
                    vals = self._site_vals()
                    capital = not any(
                        isinstance(c, dict)
                        and num(c.get('owner', self.my_player_id),
                                self.my_player_id) == self.my_player_id
                        for c in as_dict(obs.get('city')).values()
                    )
                    best = None
                    for dx in range(-CARRIER_GOAL_RADIUS, CARRIER_GOAL_RADIUS + 1):
                        for dy in range(-CARRIER_GOAL_RADIUS, CARRIER_GOAL_RADIUS + 1):
                            distance = max(abs(dx), abs(dy))
                            if distance == 0:
                                continue
                            if best is not None and distance >= best[0]:
                                continue
                            try:
                                site = evaluate_site(map_obs, int(x) + dx, int(y) + dy,
                                                     size=1, vals=vals)
                            except Exception:  # noqa: BLE001
                                continue
                            if site.viable:
                                best = (distance, int(x) + dx, int(y) + dy)
                    if best is not None:
                        distance, gx, gy = best
                        site = evaluate_site(map_obs, gx, gy, size=1, vals=vals)
                        rate = self._carrier_rate(site, capital)
                        if rate > 0.0:
                            result = ((gx, gy), rate)
        except Exception:  # noqa: BLE001 - поиск цели не должен ломать извлечение
            result = None
        cache[cache_key] = result
        return result

    def carrier_delay_rate(self, obs: dict[str, Any], unit_id: str) -> float:
        """Цена простоя носителя НА ЕГО ТЕКУЩЕЙ клетке (опции/ход)."""
        vals = self._site_vals()
        if 'rules.food_cost' in vals:
            vals['FOOD_COST'] = vals['rules.food_cost']
        map_obs = as_dict(obs.get('map'))
        unit_obs = as_dict(obs.get('unit')).get(unit_id)
        if unit_obs is None:
            unit_obs = as_dict(obs.get('unit')).get(str(unit_id))
        if not isinstance(unit_obs, dict):
            return 0.0
        capital = not any(
            isinstance(c, dict)
            and num(c.get('owner', self.my_player_id), self.my_player_id) == self.my_player_id
            for c in as_dict(obs.get('city')).values()
        )
        return self._carrier_rate(self._carrier_site(unit_obs, map_obs, vals), capital)

    def _site_vals(self) -> dict[str, Any]:
        """Значения модели с порогом площадки для ПЕРВОГО города (§10.27).

        Одно правило на проект: прогноз берёт порог из `first_city_food_gate` в
        `brain/forecast/live.py`, прежний путь — здесь. Расхождение означало бы, что
        один путь основывает город на бедном старте, а второй стоит вечно, и A/B
        сравнивал бы разные правила вместо разных политик.
        """
        vals = dict(self.model.values())
        if getattr(self, "_no_cities", False):
            vals["SITE_MIN_FOOD"] = _first_city_food_gate(getattr(self, "_turn", 1))
        return vals

    def _carrier_site(self, unit_obs: dict[str, Any], map_obs: dict[str, Any],
                      vals: dict[str, Any]) -> Optional[SiteEvaluation]:
        """Площадка вокруг носителя, если она вообще годится для города.

        Возвращает ``None``, если носитель вне карты или площадка не прошла
        гейт минимального качества: тогда цена задержки падает до пола, потому
        что роста, который теряется, здесь просто нет.
        """
        if not map_obs:
            return None
        x, y = unit_obs.get('x'), unit_obs.get('y')
        if x is None or y is None:
            return None
        try:
            site = evaluate_site(map_obs, int(x), int(y), size=1, vals=vals)
        except Exception:  # pragma: no cover - защита от неожиданной формы карты
            return None
        return site if site.viable else None

    # ── Bridge calibration (state-derived action pricing) ─────────────────

    def _compute_bridge_calibration(self, obs: dict[str, Any]) -> BridgeCalibration:
        """Price the actions the bridge cannot look up in a measured table.

        Three quantities make the agent's incentives real instead of guessed:
        what a new city is worth *here* (so founding is a difference, not a
        constant), what one more improvement is worth to *this* city, and what a
        technology's unlocked set is worth per turn of research (so
        `research_tech` stops being a 0.0000 action).
        """
        unit_catalog: dict[str, float] = {}
        improvement_catalog: dict[str, float] = {}

        # Site work (city value on the carrier's own tile, and the gain from
        # walking to a better one) needs the same view of the rules and the map.
        vals = self._site_vals()
        if 'rules.food_cost' in vals:
            vals['FOOD_COST'] = vals['rules.food_cost']
        map_obs = as_dict(obs.get('map'))
        capital = not any(
            isinstance(c, dict)
            and num(c.get('owner', self.my_player_id), self.my_player_id) == self.my_player_id
            for c in as_dict(obs.get('city')).values()
        )

        # A technology carries the full parameter set of everything it unlocks,
        # which is the densest catalogue of unit and improvement types available
        # in the observation.
        for tech_obs in as_dict(obs.get('tech')).values():
            if not isinstance(tech_obs, dict):
                continue
            for spec in as_list(tech_obs.get('sup_units')):
                if not isinstance(spec, dict):
                    continue
                name = str(spec.get('rule_name') or spec.get('name') or '').strip()
                if name and name not in unit_catalog:
                    unit_catalog[name] = unit_options(spec, model=self.model)[0]
            for spec in as_list(tech_obs.get('sup_improvements')):
                if not isinstance(spec, dict):
                    continue
                name = str(spec.get('rule_name') or spec.get('name') or '').strip()
                if name and name not in improvement_catalog:
                    improvement_catalog[name] = improvement_options(spec,
                                                                   model=self.model)

        site_options, nonviable, site_report = self._carrier_site_options(obs)
        move_gains, move_report = self._site_move_gains(obs, capital, vals, map_obs)
        work_gains, work_report = self._terrain_work_gains(obs, vals, map_obs)
        contested = self.model.contested()

        return BridgeCalibration(
            new_city_options=self._new_city_options(obs),
            new_city_options_by_unit=site_options,
            nonviable_carrier_sites=nonviable,
            site_report=site_report,
            site_move_gain_by_unit=move_gains,
            site_move_report=move_report,
            terrain_work_gain_by_unit=work_gains,
            terrain_work_report=work_report,
            model_values=dict(vals),
            # Семейства, которые агент уже пробовал: у них надбавка за незнание
            # убывает и обнуляется на CONFIDENCE_K пробах. Отсутствующее семейство
            # = 0 проб = полная надбавка.
            experiment_attempts=dict(self.model.experiment_attempts),
            contested_keys=contested,
            confidence_by_key={item.get('key', ''): self.model.confidence(item.get('key', ''))
                               for item in contested},
            improvement_gain=self._improvement_gains(obs),
            unit_type_options=unit_catalog,
            improvement_options=improvement_catalog,
            tech_research_gain=self._tech_research_gains(obs),
        )

    def _carrier_site_options(self, obs: dict[str, Any]) -> tuple[
            dict[str, float], list[str], dict[str, dict[str, Any]]]:
        """Цена города на площадке каждого носителя (и гейт качества).

        `build_city` не несёт координат: город появляется на клетке, где стоит
        носитель. Поэтому выбор площадки — это выбор, **куда идти**, и дельта
        основания обязана считаться по площадке *под носителем*, а не по
        среднему городу империи. Площадка, не прошедшая гейт, в цены не попадает
        вовсе (doc §3: негодное вырезается, а не штрафуется) и перечисляется
        отдельно, чтобы решение было проверяемым.
        """
        vals = self._site_vals()
        if 'rules.food_cost' in vals:
            vals['FOOD_COST'] = vals['rules.food_cost']
        map_obs = as_dict(obs.get('map'))
        capital = not any(
            isinstance(c, dict)
            and num(c.get('owner', self.my_player_id), self.my_player_id) == self.my_player_id
            for c in as_dict(obs.get('city')).values()
        )
        by_unit: dict[str, float] = {}
        nonviable: list[str] = []
        report: dict[str, dict[str, Any]] = {}
        if not map_obs:
            return by_unit, nonviable, report
        for unit_id, unit_obs in as_dict(obs.get('unit')).items():
            if not isinstance(unit_obs, dict) or not is_population_carrier(unit_obs):
                continue
            x, y = unit_obs.get('x'), unit_obs.get('y')
            if x is None or y is None:
                continue
            entity_id = f"unit_{unit_id}"
            self._carrier_pos[entity_id] = (int(x), int(y))
            try:
                site = evaluate_site(map_obs, int(x), int(y), size=1, vals=vals)
            except Exception:  # pragma: no cover
                continue
            info = site.as_dict()
            size_h, _ = size_at_horizon(site, turns=int(vals.get('GROWTH_HORIZON_TURNS', 15)),
                                        size=1, food_cost=float(vals.get('FOOD_COST', 2.0)))
            info['size_at_horizon'] = size_h
            info['delay_per_turn'] = round(
                counterfactual_growth_sink_per_turn(site if site.viable else None, vals), 4)
            report[entity_id] = info
            if not site.viable:
                nonviable.append(entity_id)
                continue
            by_unit[entity_id] = self._site_city_value(site, capital)
            # Запоминаем прогноз выхода площадки по каналам: он понадобится
            # позже, чтобы сверить его с ФАКТИЧЕСКИМ выходом основанного города.
            self._carrier_site_pred[entity_id] = {
                "food": float(site.food), "shield": float(site.shields),
                "trade": float(site.trade),
            }
        if by_unit:
            # Прогноз «сколько будет стоить основанный город» — чтобы на
            # следующем ходу сравнить его с фактом (мир не публикует наши
            # коэффициенты, единственный путь их уточнить — такая пара).
            for entity_id, value in by_unit.items():
                self._city_predictions[entity_id] = value
        return by_unit, nonviable, report

    def _site_move_gains(self, obs: dict[str, Any], capital: bool, vals: dict[str, Any],
                         map_obs: dict[str, Any]) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
        """Сколько даёт переход к лучшей площадке в пределах хода носителя.

        Носитель на бесплодной земле не может основать город (гейт), поэтому его
        потенциальная ценность реализуема **только через перемещение**. Здесь
        считается выигрыш: ценность города на лучшей достижимой площадке минус
        ценность города там, где носитель стоит сейчас.

        Выигрыш дисконтируется тем же `W_FUTURE_UNIT`, что и потенциал юнита:
        город ещё не основан, это по-прежнему будущая возможность, а не
        наличная. Сравнение с ценой задержки (сток §7) тогда честное: идти
        3 хода за площадкой +X стоит 3 × сток, и выигрыш обязан это перебить.
        """
        gains: dict[str, float] = {}
        report: dict[str, dict[str, Any]] = {}
        if not map_obs:
            return gains, report
        disc = float(vals.get('W_FUTURE_UNIT', 0.35))
        for unit_id, unit_obs in as_dict(obs.get('unit')).items():
            if not isinstance(unit_obs, dict) or not is_population_carrier(unit_obs):
                continue
            x, y = unit_obs.get('x'), unit_obs.get('y')
            if x is None or y is None:
                continue
            entity_id = f"unit_{unit_id}"
            try:
                here = evaluate_site(map_obs, int(x), int(y), size=1, vals=vals)
            except Exception:  # pragma: no cover
                continue
            current_value = self._site_city_value(here, capital) if here.viable else 0.0

            reach = max(1, int(num(spec_field(unit_obs, 'move_rate', 1), 1)))
            best_value, best_target = current_value, None
            for dx in range(-reach, reach + 1):
                for dy in range(-reach, reach + 1):
                    if dx == 0 and dy == 0:
                        continue
                    try:
                        cand = evaluate_site(map_obs, int(x) + dx, int(y) + dy,
                                             size=1, vals=vals)
                    except Exception:  # pragma: no cover
                        continue
                    if not cand.viable:
                        continue
                    value = self._site_city_value(cand, capital)
                    if value > best_value + 1e-9:
                        best_value, best_target = value, {
                            **cand.as_dict(), 'dx': dx, 'dy': dy,
                            'target_x': int(x) + dx, 'target_y': int(y) + dy,
                        }
            raw = max(0.0, best_value - current_value)
            if raw <= 0.0:
                continue
            gains[entity_id] = disc * raw
            report[entity_id] = {
                'current_value': round(current_value, 3),
                'best_value': round(best_value, 3),
                'raw_gain': round(raw, 3),
                'discounted_gain': round(gains[entity_id], 3),
                'reach': reach,
                'target': best_target,
            }
        return gains, report

    def _site_city_value(self, site: SiteEvaluation, capital: bool) -> float:
        """Ценность города на площадке — той же формулой, что и настоящий город.

        Плюс ОПЦИИ площадки (берег, ресурсы): они не вход клетки, а
        дополнительные пути развития, поэтому входят как опции, а не как еда.
        """
        return self._site_city_value_at(site, capital, 1)

    def _site_city_value_at(self, site: SiteEvaluation, capital: bool, size: int) -> float:
        """Ценность города размера `size` на площадке — формулой города.

        Размер входит и в `CITY_BASE + CITY_POP × size`, и в амбар, поэтому рост
        считается тем же кодом, что и настоящий город (пункт 3): множители
        площадки влияют на цену роста, а не подменяются плоским «житель».
        """
        probe = hypothetical_city_obs(site, size=size, capital=capital)
        return city_options(probe, garrison=0, model=self.model) + site.option_bonus

    def _terrain_work_gains(self, obs: dict[str, Any], vals: dict[str, Any],
                            map_obs: dict[str, Any]) -> tuple[
            dict[str, dict[str, float]], dict[str, dict[str, Any]]]:
        """Сколько опций принесёт городу работа рабочего на его клетке.

        Работа ставит на клетку экстру (ирригация, шахта, дорога), выход клетки
        растёт, а клетку обрабатывает город — значит выгода адресуется **городу,
        в область которого попадает клетка** (21 клетка, радиус 2). Считается
        она той же формулой города, что и всё остальное: сравниваются два снимка
        города — с текущими излишками и со сдвинутыми на измеренный эффект.

        Если экстра на клетке уже стоит, работа бессмысленна (0). Если эффект не
        измерен или города рядом нет — тоже 0: правдоподобное число вместо
        измерения здесь было бы обманом агента.
        """
        gains: dict[str, dict[str, float]] = {}
        report: dict[str, dict[str, Any]] = {}
        if not map_obs:
            return gains, report
        own_cities = {
            cid: c for cid, c in as_dict(obs.get('city')).items()
            if isinstance(c, dict)
            and num(c.get('owner', self.my_player_id), self.my_player_id) == self.my_player_id
        }
        if not own_cities:
            return gains, report
        discount = float(vals.get('W_FUTURE_UNIT', 0.35))
        for unit_id, unit_obs in as_dict(obs.get('unit')).items():
            if not isinstance(unit_obs, dict):
                continue
            x, y = unit_obs.get('x'), unit_obs.get('y')
            if x is None or y is None:
                continue
            if not truthy(spec_field(unit_obs, 'worker', False)):
                continue  # работы ставит рабочий, не любой юнит
            terrain, extras = tile_terrain_extras(map_obs, int(x), int(y))
            per_extra: dict[str, float] = {}
            for extra in sorted(set(WORK_ACTION_EXTRA.values())):
                effect = tile_effect(extra, terrain, extras, vals)
                if effect is None or effect == (0.0, 0.0, 0.0):
                    continue
                city_id, city_obs = self._city_working_tile(int(x), int(y), own_cities)
                if city_obs is None:
                    continue
                base = city_options(city_obs, garrison=0, model=self.model)
                shifted = dict(city_obs)
                for key, delta in (('surplus_food', effect[0]),
                                   ('surplus_shield', effect[1]),
                                   ('surplus_trade', effect[2])):
                    shifted[key] = num(shifted.get(key, 0), 0) + delta
                gain = max(0.0, city_options(shifted, garrison=0, model=self.model) - base)
                if gain <= 0.0:
                    continue
                per_extra[extra] = discount * gain
                report.setdefault(f"unit_{unit_id}", {})[extra] = {
                    'tile': [int(x), int(y)], 'terrain': terrain,
                    'extras_present': list(extras), 'effect': list(effect),
                    'city': f"city_{city_id}", 'gain': round(per_extra[extra], 4),
                }
            if per_extra:
                gains[f"unit_{unit_id}"] = per_extra
        return gains, report

    def _city_working_tile(self, x: int, y: int, own_cities: dict[str, Any]) -> tuple[
            str, Optional[dict[str, Any]]]:
        """Город, в чью область влияния (21 клетка) попадает клетка (x, y)."""
        best: tuple[str, Optional[dict[str, Any]]] = ("", None)
        best_dist = 1e9
        for city_id, city_obs in own_cities.items():
            cx, cy = city_obs.get('x'), city_obs.get('y')
            if cx is None or cy is None:
                continue
            dx, dy = abs(int(cx) - x), abs(int(cy) - y)
            if max(dx, dy) > 2 or (dx == 2 and dy == 2):
                continue  # вне 21 клетки (квадрат 5×5 без углов)
            dist = dx + dy
            if dist < best_dist:
                best, best_dist = (str(city_id), city_obs), dist
        return best

    def _new_city_options(self, obs: dict[str, Any]) -> float:
        """Options a freshly founded city would have, in this empire's conditions.

        A new settlement starts with one citizen, an empty food box and no
        improvements, so the honest estimate reuses the *land and economy* of the
        cities we already hold (same tiles, same multipliers) while setting the
        things a new city does not yet have to zero. With no city to learn from,
        the structural floor is used: CITY_BASE + CITY_POP.
        """
        best = 0.0
        for city_obs in as_dict(obs.get('city')).values():
            if not isinstance(city_obs, dict):
                continue
            if num(city_obs.get('owner', self.my_player_id), self.my_player_id) != self.my_player_id:
                continue
            probe = dict(city_obs)
            probe['size'] = 1
            probe['food_stock'] = 0
            probe['improvements'] = []
            best = max(best, city_options(probe, garrison=0, model=self.model))
        if best <= 0.0:
            best = (self.model.values()['CITY_BASE']
                    + self.model.values()['CITY_POP'])
        return best

    def _improvement_gains(self, obs: dict[str, Any]) -> dict[str, float]:
        """Per-city option gain from one more standing improvement."""
        gains: dict[str, float] = {}
        for city_id, city_obs in as_dict(obs.get('city')).items():
            if not isinstance(city_obs, dict):
                continue
            if num(city_obs.get('owner', self.my_player_id), self.my_player_id) != self.my_player_id:
                continue
            entity_id = f"city_{city_id}"
            garrison = self._garrison_counts(obs).get((city_obs.get('x'), city_obs.get('y')), 0)
            current = city_options(city_obs, garrison=garrison, model=self.model)
            count = sum(1 for v in as_list(city_obs.get('improvements')) if truthy(v))
            probe = dict(city_obs)
            probe['improvements'] = [True] * (count + 1)
            gains[entity_id] = max(0.0, city_options(probe, garrison=garrison,
                                                    model=self.model) - current)
        return gains

    def _tech_research_gains(self, obs: dict[str, Any]) -> dict[str, float]:
        """Options per turn unlocked by researching each unknown technology.

        Срок текущей технологии считается по **измеренному** драйверу науки:

            наука_за_ход = round(Σ prod_trade своих городов × ставка науки / 100)

        Раньше здесь бралось `max(1.0, player['science'])` — то есть поле, которое
        прогресс не двигает вообще (измерено на трёх картах: рост `bulbs_researched`
        равен `round(торговля × ставка)`, а `player['science']` — это СТАВКА, 60, и
        она не совпала с ростом ни в одном ходу). Из-за этого числа по исследованиям
        были завышены примерно на два порядка.

        Стоимость публикуется только для ТЕКУЩЕЙ технологии; остальные оцениваются
        номинальным сроком (`tech.nominal_turns`) — и это здесь названо прямо, а не
        спрятано.
        """
        player = player_record(obs, self.my_player_id)
        current_tech = player.get('researching')
        cost = num(player.get('researching_cost', 0), 0)
        bulbs = num(player.get('bulbs_researched', 0), 0)
        rate = num(player.get('science', 0), 0)
        trade = 0.0
        for city in as_dict(obs.get('city')).values():
            if not isinstance(city, dict):
                continue
            if str(city.get('owner', self.my_player_id)) != str(self.my_player_id):
                continue
            trade += num(city.get('prod_trade', 0), 0)
        per_turn = round(trade * rate / 100.0)

        gains: dict[str, float] = {}
        for tech_id, tech_obs in as_dict(obs.get('tech')).items():
            if not isinstance(tech_obs, dict):
                continue
            if num(tech_obs.get('inv_state', 0), 0) > 0.5:
                continue  # already known: nothing left to research
            unlocked = (tech_options(tech_obs, as_known=True, model=self.model)
                        - self.model.values()['TECH_BASE_OPTIONS'])
            if unlocked <= 0.0:
                continue
            if current_tech is not None and num(tech_id, -1) == num(current_tech, -2):
                if per_turn <= 0.0:
                    # Науки за ход нет — срок неизвестен. Публиковать «номинальный»
                    # вместо известного нельзя: это было бы выдуманное число.
                    continue
                turns = max(1.0, math.ceil(max(0.0, cost - bulbs) / per_turn))
            else:
                turns = self.model.values()['tech.nominal_turns']
            gains[f"tech_{tech_id}"] = unlocked / turns
        return gains

    # ── World-model reconciliation ────────────────────────────────────────

    UNIT_TYPE_FACT_FIELDS: tuple[str, ...] = (
        'hp', 'attack_strength', 'defense_strength', 'firepower', 'move_rate',
        'vision_radius_sq', 'worker', 'can_transport', 'build_cost',
        'pop_cost', 'convert_time', 'converted_to',
    )

    def _reconcile_world_model(self, obs: dict[str, Any], turn: int) -> None:
        """Check the model against the world, and let the world win.

        This is the refinement loop's entry point: it runs on every extracted
        turn, costs nothing but the fields already read, and leaves an audit
        trail (`model.reconciliations`) that answers the honest question — how
        far does the pre-installed model actually agree with this stand?

        Only *ruleset-level* facts are reconciled here: rules the model claims
        (``granary_size = 10 × (size + 1)``, the city radius, unit-type
        parameters). Instance facts (a city's size, a unit's health) are never
        written into the model — they are state, and state is always read from
        the world. Coefficients of our own formulas are not observable at all, so
        they are only ever refined statistically (``WorldModel.record_pair`` /
        ``refine_coefficient``), never from a single sighting.
        """
        model = self.model

        # 1. City rules the model claims.
        for city_obs in as_dict(obs.get('city')).values():
            if not isinstance(city_obs, dict):
                continue
            size = num(city_obs.get('size', city_obs.get('population', 1)), 1)
            granary = num(city_obs.get('granary_size', 0), 0)
            if granary > 0 and size + 1 > 0:
                model.observe('city.granary_per_size', granary / (size + 1), turn,
                              source=Provenance.RULESET,
                              evidence=f'granary_size={granary:g} at size {size:g}',
                              tol=0.5)
            radius = num(city_obs.get('city_radius_sq', 0), 0)
            if radius > 0:
                model.observe('city.radius_sq', radius, turn,
                              source=Provenance.RULESET,
                              evidence='city_radius_sq of an observed city')

        # 2. Unit-type facts: first correct the ones the model claims (hit
        #    points), then register everything else the type publishes — this is
        #    how the model's type table gets built out of real observations.
        for unit_obs in as_dict(obs.get('unit')).values():
            if not isinstance(unit_obs, dict):
                continue
            name = str(spec_field(unit_obs, 'rule_name', '') or '').strip().lower()
            if not name:
                continue
            for field in self.UNIT_TYPE_FACT_FIELDS:
                value = spec_field(unit_obs, field, None)
                if value is None:
                    continue
                model.observe(f'unit_type.{name}.{field}', value, turn,
                              source=Provenance.RULESET,
                              evidence=f'observed {name} ({field})')

    #: Ruleset constants the model claims, mapped to their names in
    #: ``obs['rules']``. Reading them from the stand instead of hardcoding them
    #: is what removed the "magic numbers" — and it immediately proved the
    #: calibration document wrong twice (minimum city distance, celebration size).
    RULESET_CLAIMS: dict[str, str] = {
        'rules.citymindist': 'citymindist',
        'rules.celebratesize': 'celebratesize',
        'rules.angrycitizen': 'angrycitizen',
        'rules.food_cost': 'food_cost',
        'rules.border_city_radius_sq': 'border_city_radius_sq',
        'rules.foodbox': 'foodbox',
        'rules.add_to_size_limit': 'add_to_size_limit',
        'rules.base_tech_cost': 'base_tech_cost',
    }

    def _reconcile_ruleset(self, obs: dict[str, Any], turn: int) -> None:
        """Reconcile the model's claimed rules against the stand's own ruleset.

        ``obs['rules']`` is the stand describing itself: the authoritative source
        for thresholds and economy constants, and a better one than any external
        document because it describes THIS ruleset as configured here. Every
        claimed key is reported to the model, so a stale claim is corrected the
        moment the world disagrees.
        """
        rules = as_dict(obs.get('rules'))
        if not rules:
            return
        for key, field in self.RULESET_CLAIMS.items():
            value = rules.get(field)
            if value is None:
                continue
            self.model.observe(key, value, turn, source=Provenance.RULESET,
                               evidence=f'rules.{field} as published by the stand')

    def _compute_tau(self, current_turn: int) -> float:
        """Compute global time-to-collapse as the remaining turns."""
        remaining_turns = max(MAX_TURNS - current_turn, 0)
        return remaining_turns * TURN_DURATION_MKS

    # ── Psi declaration ───────────────────────────────────────────────────

    def _compute_psi(
        self,
        entities: dict[str, EntityState],
        turn: int,
    ) -> dict[str, str]:
        """Compute psi measurement declaration (DOF-SPEC §3.4)."""
        declaration = {
            'psi_id': 'dof-model-civ-extractor-v1',
            'turn': turn,
            'lens_set': ['variety', 'freedom', 'resilience'],
            'entity_count': len(entities),
            'entities': {
                eid: {
                    'dof_options': f"{ent.dof_count:.6f}",
                    'is_collapse_source': ent.is_collapse_source,
                    'dof_known': ent.dof_known,
                }
                for eid, ent in sorted(entities.items())
            },
        }

        # Canonical serialization (DOF-SPEC §3.4.3)
        canonical = json.dumps(
            declaration,
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
        ).encode('utf-8')

        return {
            'id': 'dof-model-civ-extractor-v1',
            'digest': hashlib.sha256(canonical).hexdigest(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# TotalDoF_index computation (DOF-SPEC §4.3)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_total_dof_index(state: SystemStateMatrix) -> float:
    """Nash log-product index: Σ ln(DoF(e)) over the calculation set, minus sinks.

    Excludes collapse sources (§4.2) and entities with unknown DoF (Axiom 5).

    DoF is an option COUNT, not a normalised score: with scores in (0, 1] every
    term ln(DoF) would be negative, so adding an entity would LOWER the index and
    a system would be "better" the fewer options it had — expansion (Axiom 1/6)
    inverted, collapse rewarded. Measured before the fix: founding five cities
    moved the index from -215.5 to -229.3.

    The system's upkeep sink (§7) is subtracted once: it is a property of the
    whole system, not of any single entity.
    """
    total = 0.0
    for entity in state.entities.values():
        if entity.is_collapse_source:
            continue
        if not entity.dof_known:
            continue
        total += math.log(max(entity.dof_count, EPSILON))
    return total - state.dof_sink
