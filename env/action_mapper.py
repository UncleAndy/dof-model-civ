"""
ActionOption mapper: CivRealm actions ↔ DOF ActionOption.

Maps available CivRealm actions to DOF-SPEC v0.9.1 ActionOption format,
estimating reversibility, duration, and DoF deltas.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, Field

from env.config import (
    TURN_DURATION_MKS,
    EPSILON,
)
from env.dof_deltas import measured_delta, SUPERSEDED_GUESSES
from env.experiments import (
    action_known,
    family_of,
    probe_bonus,
    uncertainty_bonus,
)
from env.wedged import is_wedged
from env.terrain_work import work_extra
from env.entity_extractor import (
    EntityState,
    SystemStateMatrix,
    as_dict,
    truthy,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Action categories
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CivAction:
    """A CivRealm action with metadata.

    ``actor_id`` keeps the exact key type used by civrealm's
    ``available_actions`` (``int`` for unit/city/gov/dipl actors, ``str`` for
    the player/tech controllers). Do **not** coerce it: the env looks the
    actor up by identity.
    """
    ctrl_type: str  # 'unit' | 'city' | 'tech' | 'gov' | 'dipl' | 'player'
    actor_id: Any
    action_name: str
    params: dict[str, Any] = field(default_factory=dict)

    def as_tuple(self) -> tuple[str, Any, str]:
        """The (ctrl_type, actor_id, action_name) triple env.step expects."""
        return (self.ctrl_type, self.actor_id, self.action_name)


# ═══════════════════════════════════════════════════════════════════════════════
# Reversibility classification
# ═══════════════════════════════════════════════════════════════════════════════

# Actions that cannot be undone
IRREVERSIBLE_ACTIONS = {
    'declare_war',
    'attack',
    'conquer_city',
    'disband',
    'destroy_improvement',
    'burn_house',
    'pillage',
}

# Actions that are partially reversible (can undo with effort)
PARTIALLY_REVERSIBLE = {
    'build_city',  # can disband but loses investment
    'build_improvement',  # can sell but loses gold
    'research_tech',  # can switch research
    'build_unit',  # can disband
    'trade_agreement',  # can cancel
    'alliance',  # can break
}

# Fully reversible actions
FULLY_REVERSIBLE = {
    'goto',
    'fortify',
    'sentry',
    'build_road',
    'irrigation',
    'mine',
    'set_tax_rate',
    'set_luxury_rate',
    'change_government',
    'patrol',
    'trade_gold',
    'trade_tech',
}

# ── Real CivRealm action names ────────────────────────────────────────────────
# Names observed in live games (scripts/inspect_actions.py) map onto the sets
# above by prefix. Keep these separate so the DOF-SPEC vocabulary stays intact
# while the bridge understands the actual wire vocabulary.
_REVERSIBLE_PREFIXES = (
    'goto',            # goto_12 -> movement is re-issuable
    'fortify',
    'sentry',
    'keep_activity',
    'irrigation',
    'mine',
    'plant',
    'cultivate',
    'transform_terrain',
    'fortress',
    'airbase',
    'road',
    'railroad',
    'set_sci_lux_tax',  # tax/luxury/science split, changeable every turn
    'change_gov',       # government can be changed back (costs a turn)
    'set_tech_goal',    # goal is advisory, freely changeable
    'chat',             # pure communication
)

_IRREVERSIBLE_PREFIXES = (
    'disband',
    'attack',
    'pillage',
    'conquer_city',
    'burn_house',
    'destroy_improvement',
    'declare_war',
)

_PARTIALLY_REVERSIBLE_PREFIXES = (
    'found_city',       # a settlement cannot be un-founded without loss
    'research_tech',    # accumulated bulbs are lost when switching
    'build_improvement',
    'build_unit',
    'build_city',
    'alliance',
    'trade_agreement',
)


def classify_reversibility(action_name: str) -> bool:
    """Return True if the action is reversible (DOF Axiom 3/4 input).

    Matching is prefix-based so parameterised names such as
    ``set_sci_lux_tax_0_40_60`` or ``goto_12`` classify as their base action.
    Unknown actions default to reversible=True (conservative for DoF: a
    reversible default avoids over-vetoing), matching the previous behaviour.
    """
    name = '' if action_name is None else str(action_name)

    # Exact DOF-SPEC vocabulary first.
    base = name.split('_')[0]
    if name in FULLY_REVERSIBLE or base in FULLY_REVERSIBLE:
        return True
    if name in IRREVERSIBLE_ACTIONS or base in IRREVERSIBLE_ACTIONS:
        return False
    if name in PARTIALLY_REVERSIBLE or base in PARTIALLY_REVERSIBLE:
        return False  # partial = effectively irreversible for DOF purposes

    # Real CivRealm vocabulary.
    for prefix in _IRREVERSIBLE_PREFIXES:
        if name.startswith(prefix):
            return False
    for prefix in _PARTIALLY_REVERSIBLE_PREFIXES:
        if name.startswith(prefix):
            return False
    for prefix in _REVERSIBLE_PREFIXES:
        if name.startswith(prefix):
            return True

    return True  # unknown -> assume reversible (do not over-veto)


# ═══════════════════════════════════════════════════════════════════════════════
# DoF delta estimation
# ═══════════════════════════════════════════════════════════════════════════════

FOUNDING_ACTIONS: tuple[str, ...] = ("build_city", "found_city", "found")

#: Moving a unit is the only way a population carrier can reach land that can
#: feed a city; CivRealm spells them `goto_<n>` / `move_<d>` / `explore`.
MOVEMENT_ACTIONS: tuple[str, ...] = ("goto", "move", "explore")


def founding_delta(entity_id: str, settler_options: float,
                   new_city_options: float) -> dict[str, float]:
    """DoF delta of founding a city with a settler (derived, not a constant).

    The action consumes the settler and creates a size-1 city, so the honest
    projection is the difference between what that city will be worth and what
    the settler is worth now — both in options, both taken from THIS state. A
    constant measured under an older model would silently keep the old
    incentive.

    Population is the game's DoF engine, so a size-1 city outranks any settler,
    which makes founding a *gain*: the opposite of the pre-population-model
    behaviour, where a city scored less than a settler (-0.3228 measured) and the
    agent correctly refused to expand.
    """
    return {entity_id: new_city_options - settler_options}


def _tech_entity_of(action_name: str) -> str | None:
    """`research_tech_Advanced Flight_2` → ``tech_2``.

    The technology controller's action names end with the technology id, which is
    the only reliable way to bind the action to the entity the extractor emits
    (``Advanced Flight`` contains a space, so a positional split cannot be
    reversed).
    """
    match = re.search(r'_(\d+)$', action_name or '')
    return f"tech_{match.group(1)}" if match else None


def estimate_dof_delta(
    action: CivAction,
    state: SystemStateMatrix,
) -> dict[str, float]:
    """
    Estimate the change in DoF for each entity caused by this action.

    Returns a dict mapping entity_id -> delta in OPTIONS (positive = gain).

    Two sources, in this order:

    1. **State-derived structure** — creating an entity, consuming one, or
       unlocking a set of them, priced by the calibrated formulas applied to the
       current state (``state.bridge``): founding a city with a settler, a city's
       ``produce_<Name>`` order, selling an improvement, researching a
       technology.
    2. **The measured table** (:mod:`env.dof_deltas`) for actions measured on a
       live game — most of them exactly zero, which is the honest value for an
       action that only spends a renewable per-turn budget.

    Anything that is neither is *unmeasured*: it gets no entry and a delta of 0.
    Guessing a plausible-looking positive here is what previously made DOF-Core
    spend whole games on actions that changed nothing, and made it trade a
    flexible Settler for a less flexible city while believing it gained.

    Controller names follow CivRealm's real vocabulary (``unit``, ``city``,
    ``tech``, ``gov``, ``dipl``, ``player``); the DOF-SPEC synonyms
    (``diplomacy``, ``economy``) are accepted too.
    """
    delta: dict[str, float] = {}
    ctrl = action.ctrl_type
    name = action.action_name
    actor = str(action.actor_id)
    entity_key = f"{ctrl}_{actor}"
    bridge = state.bridge

    # 0. An action measured to wedge the stand is cut, not priced. This is the one
    #    case where the honest value is not zero: zero would look like "no effect"
    #    and let a curious agent pick it again in the next match, killing that
    #    match too. Cutting it removes it from the shortlist entirely.
    position = getattr(state, "positions", {}).get(entity_key)
    wedge_context = None
    if isinstance(position, (tuple, list)) and len(position) == 2:
        try:
            wedge_context = {"position": [int(position[0]), int(position[1])]}
        except (TypeError, ValueError):
            wedge_context = None
    if is_wedged(ctrl, name, context=wedge_context):
        return {}

    # 1. Founding is a difference between two states, not a constant.
    if ctrl == 'unit' and any(name.startswith(a) for a in FOUNDING_ACTIONS):
        entity = state.entities.get(entity_key)
        if entity is not None:
            # `build_city` carries no coordinates — the city rises on the tile the
            # unit stands on — so the value of founding is the value of the city
            # **at this unit's own site**, which the extractor priced from the map.
            # A site that failed the quality gate has no price at all: the action
            # is excised (no invented gain), and the delay sink keeps pushing the
            # carrier to walk somewhere that can actually feed a city.
            if entity_key in bridge.nonviable_carrier_sites:
                return {}
            site_options = bridge.new_city_options_by_unit.get(
                entity_key, bridge.new_city_options)
            delta = founding_delta(entity_key, entity.dof_count, site_options)
            # Founding is ALSO the experiment that settles how much a city is
            # worth here: if the world keeps arguing about that value, a real
            # foundation is the only way to find out. Paying the probe bonus here
            # matters because the founding branch returns before the generic
            # unmeasured treatment below — otherwise the bonus would be
            # unreachable exactly where the evidence is produced.
            probe = probe_bonus(ctrl, name, bridge.contested_keys,
                                lambda key: bridge.experiment_attempts.get(
                                    family_of(name), 0),
                                bridge.model_values)
            if probe:
                delta[entity_key] = delta.get(entity_key, 0.0) + probe
            return delta

    # 1b. Walking a population carrier toward better land is worth the *founding
    #     value* it unlocks: a settler on barren ground cannot found at all (the
    #     quality gate excises it), so the population engine is only reachable by
    #     moving. The gain is discounted (W_FUTURE_UNIT) because the city is still
    #     an unrealised option, and it is charged against the delay sink the
    #     carrier accrues every turn it stays undeployed — so the agent walks only
    #     when the destination is worth the walk.
    if ctrl == 'unit' and entity_key in bridge.site_move_gain_by_unit:
        if any(name.startswith(p) for p in MOVEMENT_ACTIONS):
            return {entity_key: bridge.site_move_gain_by_unit[entity_key]}

    # 1c. Terrain work: a worker's irrigation/mine/road raises the tile's output,
    #     and the city that works that tile is worth more. The effect is taken
    #     from the MEASURED table (never from documentation), so an unmeasured
    #     work action stays at zero instead of receiving a plausible number.
    if ctrl == 'unit' and entity_key in bridge.terrain_work_gain_by_unit:
        extra = work_extra(name)
        if extra:
            gain = bridge.terrain_work_gain_by_unit[entity_key].get(extra)
            if gain:
                return {entity_key: gain}

    # 2. Production orders: `produce_<Name>` builds either a unit or an
    #    improvement. A unit adds its own options to the system; an improvement
    #    raises its city's first factor, capped. Both are read from the
    #    observation's own catalogue of types, never from a guess.
    if ctrl == 'city' and name.startswith('produce_'):
        target = name[len('produce_'):].strip()
        if target in bridge.unit_type_options:
            return {entity_key: bridge.unit_type_options[target]}
        if target in bridge.improvement_options:
            gain = bridge.improvement_gain.get(entity_key, 0.0)
            return {entity_key: gain} if gain else {}
        return {}

    if ctrl == 'city' and name.startswith('city_sell_improvement_'):
        gain = bridge.improvement_gain.get(entity_key, 0.0)
        return {entity_key: -gain} if gain else {}

    # 3. Research: the technology's unlocked set, as a per-turn rate.
    if ctrl == 'tech' and name.startswith('research_tech'):
        tech_entity = _tech_entity_of(name)
        if tech_entity and tech_entity in state.entities:
            gain = bridge.tech_research_gain.get(tech_entity, 0.0)
            return {tech_entity: gain} if gain else {}

    # 4. Measured value wins for everything already measured on a live game.
    measured = measured_delta(ctrl, name)
    if measured is not None:
        if entity_key in state.entities:
            delta[entity_key] = measured
        else:
            # e.g. unit actions whose entity is not modelled: attribute to the
            # first entity of the same controller so the core still sees it.
            for entity in state.entities.values():
                if entity.entity_id.startswith(f"{ctrl}_"):
                    delta[entity.entity_id] = measured
                    break
        return delta

    # 5. Unmeasured — no invented number for the effect, but NOT silence either.
    #    An action whose effect was never measured is an experiment: by Axiom 5/7
    #    an unknown outcome is not "zero options", so it carries the price of
    #    finding out (`uncertainty_bonus`), which decays as the family is tried
    #    (`experiment_confidence`). A *measured* zero (e.g. road, measured 0.0 on
    #    this stand) gets nothing: that is knowledge, not ignorance. Actions that
    #    would settle a key the world keeps contesting get the probe bonus on top.
    #    The experiment must be *recoverable*: paying for a probe with an
    #    irreversible action (attack, pillage, disband…) would buy knowledge by
    #    spending options we can never get back — exactly what Axiom 3/4 forbid.
    #    Irreversible unmeasured actions therefore keep their previous treatment:
    #    no invented number, and the Axiom-4 penalty is the only thing the core
    #    sees, which is what vetoes them.
    if not action_known(ctrl, name) and classify_reversibility(name):
        attempts = bridge.experiment_attempts.get(family_of(name), 0)
        bonus = uncertainty_bonus(
            ctrl, name, bridge.model_values, attempts)
        bonus += probe_bonus(ctrl, name, bridge.contested_keys,
                             lambda key: attempts,
                             bridge.model_values)
        if bonus > 0:
            target = entity_key if entity_key in state.entities else next(
                (e.entity_id for e in state.entities.values()
                 if e.entity_id.startswith(f"{ctrl}_")), None)
            if target is not None:
                delta[target] = delta.get(target, 0.0) + bonus
            return delta
    return delta


def estimate_resource_delta(action: CivAction) -> dict[str, dict[str, float]]:
    """
    Estimate resource consumption/production for this action.

    Returns nested dict: entity_id -> {resource: delta}.
    Negative = consumption, positive = production.
    """
    resources: dict[str, dict[str, float]] = {}

    if action.ctrl_type == 'city':
        entity_id = f"city_{action.actor_id}"
        name = action.action_name

        if name.startswith('produce_'):
            # A production order spends shields; its exact price is the built
            # type's cost, which the observation carries per type.
            resources[entity_id] = {'production': -1.0}
        elif name.startswith('city_buy_production'):
            resources[entity_id] = {'gold': -1.0}
        elif name.startswith('city_sell_improvement_'):
            resources[entity_id] = {'gold': 1.0}

    elif action.ctrl_type == 'unit':
        entity_id = f"unit_{action.actor_id}"
        name = action.action_name

        if name == 'build_city':
            resources[entity_id] = {'production': -30.0}
        elif name == 'build_road':
            resources[entity_id] = {'moves': -1.0}

    return resources


# ═══════════════════════════════════════════════════════════════════════════════
# ActionOption generator
# ═══════════════════════════════════════════════════════════════════════════════

class ActionOptionGenerator:
    """
    Generates DOF ActionOption candidates from CivRealm available_actions.
    """

    def generate_from_state(
        self,
        state: SystemStateMatrix,
        available_actions: dict[str, dict[str, dict[str, Any]]],
        valid_only: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Generate ActionOption candidates from available actions.

        Parameters
        ----------
        state : SystemStateMatrix
            Current DOF state.
        available_actions : dict
            CivRealm format: {ctrl_type: {actor_id: {action_name: params}}}.
        valid_only : bool
            Keep only actions civrealm will accept. CivRealm strips actions
            whose param dict is empty before offering them as valid
            (BaseAgent.get_next_valid_actor), so an action with falsy params is
            rejected by the server and must not be offered as a candidate.

        Returns
        -------
        List of ActionOption dicts. Each carries the structured origin of the
        action (``ctrl_type`` / ``actor_id`` / ``action_name``) so callers never
        have to parse ``option_id`` back — actor ids and action names may
        themselves contain underscores (``cur_player``,
        ``set_sci_lux_tax_0_40_60``) and actor ids may be ints or strings.
        """
        candidates: list[dict[str, Any]] = []

        for ctrl_type, actors in as_dict(available_actions).items():
            for actor_id, actions in as_dict(actors).items():
                for action_name, params in as_dict(actions).items():
                    # A numpy array here would raise on `not params`; civrealm
                    # rejects an action whose params are empty, so the test has to
                    # work on arrays too.
                    if valid_only and not truthy(params):
                        continue

                    civ_action = CivAction(
                        ctrl_type=ctrl_type,
                        actor_id=actor_id,          # keep the key type as-is
                        action_name=action_name,
                        params=params if isinstance(params, dict) else {},
                    )

                    option = self._create_option(civ_action, state)
                    if option is not None:
                        candidates.append(option)

        return candidates

    def _create_option(
        self,
        action: CivAction,
        state: SystemStateMatrix,
    ) -> Optional[dict[str, Any]]:
        """Create a single ActionOption dict from CivAction."""
        option_id = f"{action.ctrl_type}_{action.actor_id}_{action.action_name}"

        # Classify reversibility
        is_reversible = classify_reversibility(action.action_name)

        # Estimate DoF delta
        dof_delta = estimate_dof_delta(action, state)

        # Estimate resource delta
        resource_delta = estimate_resource_delta(action)

        # Duration estimate
        duration_mks = TURN_DURATION_MKS  # default 1 turn

        # Description
        description = f"{action.ctrl_type}: {action.actor_id} {action.action_name}"

        entity_key = f"{action.ctrl_type}_{action.actor_id}"

        return {
            'option_id': option_id,
            # Authoritative, unambiguous origin of the action.
            'ctrl_type': action.ctrl_type,
            'actor_id': action.actor_id,
            'action_name': action.action_name,
            'params': action.params,
            'description': description,
            'projected_dof_delta': dof_delta,
            'projected_resource_delta': resource_delta,
            'requires': list(resource_delta.get(entity_key, {}).keys()),
            'discovers': [],
            'is_reversible': is_reversible,
            'estimated_duration_mks': duration_mks,
            'projected_tau_delta': 0.0,
        }
