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
    """A named strategy with action preferences."""
    name: str
    description: str
    preferred_unit_actions: list[str] = field(default_factory=list)
    preferred_city_actions: list[str] = field(default_factory=list)
    preferred_diplomacy_actions: list[str] = field(default_factory=list)
    preferred_economy_actions: list[str] = field(default_factory=list)
    priority: str = "balanced"  # 'military', 'economic', 'science', 'balanced'


# Pre-defined strategies
DEFENSIVE = StrategyTemplate(
    name="defensive",
    description="Fortify borders, strengthen cities, avoid conflict",
    preferred_unit_actions=['fortify', 'sentry', 'goto'],
    preferred_city_actions=['build_unit', 'build_improvement'],
    preferred_diplomacy_actions=['peace_treaty', 'alliance'],
    preferred_economy_actions=['set_tax_rate', 'set_luxury_rate'],
    priority="military",
)

EXPANSIONIST = StrategyTemplate(
    name="expansionist",
    description="Build new cities, claim territory, grow population",
    preferred_unit_actions=['build_city', 'goto', 'build_road'],
    preferred_city_actions=['build_unit', 'research_tech'],
    preferred_diplomacy_actions=['trade_agreement', 'peace_treaty'],
    preferred_economy_actions=['set_tax_rate'],
    priority="balanced",
)

ECONOMIC = StrategyTemplate(
    name="economic",
    description="Maximize gold, trade, infrastructure",
    preferred_unit_actions=['build_road', 'goto', 'pillage'],
    preferred_city_actions=['build_improvement', 'research_tech', 'buy_improvement'],
    preferred_diplomacy_actions=['trade_agreement', 'trade_tech', 'trade_gold'],
    preferred_economy_actions=['set_tax_rate', 'set_luxury_rate'],
    priority="economic",
)

TECHNOLOGICAL = StrategyTemplate(
    name="technological",
    description="Rush key technologies, invest in research",
    preferred_unit_actions=['goto', 'fortify', 'sentry'],
    preferred_city_actions=['research_tech', 'build_improvement', 'build_unit'],
    preferred_diplomacy_actions=['research_pact', 'trade_tech'],
    preferred_economy_actions=['set_luxury_rate'],
    priority="science",
)

DIPLOMATIC = StrategyTemplate(
    name="diplomatic",
    description="Form alliances, trade agreements, peace treaties",
    preferred_unit_actions=['goto', 'fortify', 'sentry'],
    preferred_city_actions=['build_improvement', 'research_tech'],
    preferred_diplomacy_actions=['alliance', 'peace_treaty', 'trade_agreement'],
    preferred_economy_actions=['set_luxury_rate', 'set_tax_rate'],
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
        List of ActionOption dicts (3-5 distinct candidates).
        """
        all_candidates = self.action_mapper.generate_from_state(state, available_actions)

        if not all_candidates:
            return []

        # Group by strategy type
        unit_actions = [c for c in all_candidates if c['option_id'].startswith('unit_')]
        city_actions = [c for c in all_candidates if c['option_id'].startswith('city_')]
        dipl_actions = [c for c in all_candidates if c['option_id'].startswith('diplomacy_')]
        econ_actions = [c for c in all_candidates if c['option_id'].startswith('economy_')]

        # Prioritize actions based on strategy
        prioritized = self._prioritize(unit_actions, city_actions, dipl_actions, econ_actions)

        # Return top 3-5
        return prioritized[:5]

    def _prioritize(
        self,
        unit_actions: list[dict],
        city_actions: list[dict],
        dipl_actions: list[dict],
        econ_actions: list[dict],
    ) -> list[dict]:
        """Sort actions by strategy preference."""
        strategy = self.strategy

        # Score each action based on strategy preference
        def score_action(action: dict) -> float:
            name = action['option_id']
            score = 0.0

            # Check if action matches preferred lists
            for pref in strategy.preferred_unit_actions:
                if pref in name:
                    score += 1.0
            for pref in strategy.preferred_city_actions:
                if pref in name:
                    score += 1.0
            for pref in strategy.preferred_diplomacy_actions:
                if pref in name:
                    score += 1.0
            for pref in strategy.preferred_economy_actions:
                if pref in name:
                    score += 1.0

            # Bonus for reversible actions (Axiom 4)
            if action.get('is_reversible', True):
                score += 0.1

            return score

        # Sort by score (descending), then by reversibility
        all_actions = unit_actions + city_actions + dipl_actions + econ_actions
        all_actions.sort(key=lambda a: (score_action(a), a.get('is_reversible', True)), reverse=True)

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
