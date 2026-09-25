"""
Heuristic strategy generator for DOF-MODEL-CIV.

Provides deterministic fallback strategies when LLM is unavailable.
Five canonical strategies based on historical patterns:

- defensive: Fortify borders, strengthen cities, avoid conflict
- expansionist: Build new cities, claim territory, grow population
- economic: Maximize gold, trade, infrastructure
- technological: Rush key technologies, invest in research
- diplomatic: Form alliances, trade agreements, peace treaties
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from env.action_mapper import CivAction, ActionOptionGenerator
from env.config import TURN_DURATION_MKS
from env.entity_extractor import SystemStateMatrix, EntityState


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy templates
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class StrategyTemplate:
    """A named strategy with action preferences.

    Preference entries are matched as **prefixes** against the action name, so
    both the DOF-SPEC vocabulary ('build_road', 'set_tax_rate') and the real
    CivRealm vocabulary ('road', 'set_sci_lux_tax_0_40_60') can be listed.
    """
    name: str
    description: str
    preferred_unit_actions: list[str] = field(default_factory=list)
    preferred_city_actions: list[str] = field(default_factory=list)
    preferred_diplomacy_actions: list[str] = field(default_factory=list)
    preferred_economy_actions: list[str] = field(default_factory=list)
    preferred_tech_actions: list[str] = field(default_factory=list)
    priority: str = "balanced"  # 'military', 'economic', 'science', 'balanced'


# Pre-defined strategies
DEFENSIVE = StrategyTemplate(
    name="defensive",
    description="Fortify borders, strengthen cities, avoid conflict",
    preferred_unit_actions=['fortify', 'fortress', 'sentry', 'keep_activity'],
    preferred_city_actions=['build_unit', 'build_improvement'],
    preferred_diplomacy_actions=['peace_treaty', 'accept_treaty', 'alliance'],
    preferred_economy_actions=['set_sci_lux_tax'],
    preferred_tech_actions=['set_tech_goal'],
    priority="military",
)

EXPANSIONIST = StrategyTemplate(
    name="expansionist",
    description="Build new cities, claim territory, grow population",
    preferred_unit_actions=['found_city', 'build_city', 'road', 'railroad', 'goto', 'irrigation'],
    preferred_city_actions=['build_unit', 'build_improvement'],
    preferred_diplomacy_actions=['add_clause', 'trade_agreement', 'peace_treaty'],
    preferred_economy_actions=['set_sci_lux_tax'],
    preferred_tech_actions=['research_tech'],
    priority="balanced",
)

ECONOMIC = StrategyTemplate(
    name="economic",
    description="Maximize gold, trade, infrastructure",
    preferred_unit_actions=['road', 'railroad', 'mine', 'plant', 'cultivate', 'goto'],
    preferred_city_actions=['build_improvement', 'buy_improvement'],
    preferred_diplomacy_actions=['add_clause', 'trade_agreement', 'trade_gold'],
    preferred_economy_actions=['set_sci_lux_tax', 'set_tax', 'set_luxury'],
    preferred_tech_actions=['research_tech'],
    priority="economic",
)

TECHNOLOGICAL = StrategyTemplate(
    name="technological",
    description="Rush key technologies, invest in research",
    preferred_unit_actions=['keep_activity', 'fortify', 'sentry'],
    preferred_city_actions=['build_improvement', 'build_unit'],
    preferred_diplomacy_actions=['add_clause', 'trade_tech'],
    preferred_economy_actions=['set_sci_lux_tax'],
    preferred_tech_actions=['research_tech', 'set_tech_goal'],
    priority="science",
)

DIPLOMATIC = StrategyTemplate(
    name="diplomatic",
    description="Form alliances, trade agreements, peace treaties",
    preferred_unit_actions=['keep_activity', 'fortify', 'sentry'],
    preferred_city_actions=['build_improvement'],
    preferred_diplomacy_actions=['alliance', 'peace_treaty', 'accept_treaty',
                                 'add_clause', 'trade_agreement'],
    preferred_economy_actions=['set_sci_lux_tax'],
    preferred_tech_actions=['set_tech_goal'],
    priority="balanced",
)

ALL_STRATEGIES = [DEFENSIVE, EXPANSIONIST, ECONOMIC, TECHNOLOGICAL, DIPLOMATIC]


# ═══════════════════════════════════════════════════════════════════════════════
# Heuristic generator
# ═══════════════════════════════════════════════════════════════════════════════

class HeuristicGenerator:
    """
    Generates ActionOption candidates using heuristic strategy templates.

    When LLM is unavailable, this provides deterministic fallback strategies
    based on historical governance patterns.
    """

    def __init__(self, strategy: Optional[StrategyTemplate] = None):
        self.strategy = strategy or DEFENSIVE
        self.action_mapper = ActionOptionGenerator()

    def generate_candidates(
        self,
        state: SystemStateMatrix,
        available_actions: dict[str, dict[str, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """
        Generate ActionOption candidates based on the current strategy.

        Parameters
        ----------
        state : SystemStateMatrix
            Current DOF state.
        available_actions : dict
            CivRealm format: {ctrl_type: {actor_id: {action_name: params}}}.

        Returns
        -------
        List of ActionOption dicts (3-5 distinct candidates), all of them
        executable: the mapper drops actions civrealm would reject.
        """
        all_candidates = self.action_mapper.generate_from_state(state, available_actions)

        if not all_candidates:
            return []

        # Group by controller, using the structured ctrl_type (never parse
        # option_id: actor ids and action names contain underscores).
        groups: dict[str, list[dict]] = {
            'unit': [], 'city': [], 'dipl': [], 'econ': [], 'tech': [],
        }
        for cand in all_candidates:
            ctrl = cand.get('ctrl_type', '')
            if ctrl == 'unit':
                groups['unit'].append(cand)
            elif ctrl == 'city':
                groups['city'].append(cand)
            elif ctrl in ('dipl', 'diplomacy'):
                groups['dipl'].append(cand)
            elif ctrl in ('gov', 'economy'):
                groups['econ'].append(cand)
            elif ctrl == 'tech':
                groups['tech'].append(cand)
            # 'player' (chat) carries no strategic value: skipped.

        prioritized = self._prioritize(
            groups['unit'], groups['city'], groups['dipl'], groups['econ'],
            groups['tech'],
        )

        # Return top 3-5
        return prioritized[:5]

    def _prioritize(
        self,
        unit_actions: list[dict],
        city_actions: list[dict],
        dipl_actions: list[dict],
        econ_actions: list[dict],
        tech_actions: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Sort actions by strategy preference (prefix match, then reversibility)."""
        strategy = self.strategy
        tech_actions = tech_actions or []

        preference_by_group: dict[str, list[str]] = {
            'unit': strategy.preferred_unit_actions,
            'city': strategy.preferred_city_actions,
            'dipl': strategy.preferred_diplomacy_actions,
            'econ': strategy.preferred_economy_actions,
            'tech': strategy.preferred_tech_actions,
        }

        def group_of(action: dict) -> str:
            ctrl = action.get('ctrl_type', '')
            if ctrl == 'unit':
                return 'unit'
            if ctrl == 'city':
                return 'city'
            if ctrl in ('dipl', 'diplomacy'):
                return 'dipl'
            if ctrl in ('gov', 'economy'):
                return 'econ'
            if ctrl == 'tech':
                return 'tech'
            return 'other'

        def score_action(action: dict) -> float:
            name = action.get('action_name', '')
            preferences = preference_by_group.get(group_of(action), [])

            score = 0.0
            for pref in preferences:
                if name.startswith(pref) or pref in name:
                    score += 1.0

            # Bonus for reversible actions (DOF Axiom 4)
            if action.get('is_reversible', True):
                score += 0.1

            return score

        # Sort by score (descending), then by reversibility
        all_actions = unit_actions + city_actions + dipl_actions + econ_actions + tech_actions
        all_actions.sort(
            key=lambda a: (score_action(a), a.get('is_reversible', True)),
            reverse=True,
        )

        return all_actions

    def select_best(
        self,
        candidates: list[dict[str, Any]],
        state: SystemStateMatrix,
    ) -> Optional[dict[str, Any]]:
        """
        Select the best action from candidates based on DoF impact.

        Simple heuristic: pick the action with highest projected DoF gain.
        """
        if not candidates:
            return None

        def net_dof_gain(candidate: dict) -> float:
            return sum(candidate.get('projected_dof_delta', {}).values())

        candidates.sort(key=net_dof_gain, reverse=True)
        return candidates[0]
