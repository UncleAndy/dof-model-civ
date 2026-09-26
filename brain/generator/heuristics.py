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

import re
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
    # Multipliers applied to the projected DoF gain per controller. Strategies
    # stay distinguishable without dropping the DoF objective: a strategy simply
    # values DoF gains in its own domains more. Missing keys default to 1.0.
    domain_weights: dict[str, float] = field(default_factory=dict)


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
    domain_weights={'unit': 1.3, 'city': 1.1, 'dipl': 0.7, 'econ': 0.9, 'tech': 0.7},
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
    domain_weights={'unit': 1.4, 'city': 1.2, 'dipl': 0.8, 'econ': 0.8, 'tech': 0.8},
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
    domain_weights={'unit': 1.0, 'city': 1.3, 'dipl': 1.0, 'econ': 1.4, 'tech': 0.9},
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
    domain_weights={'unit': 0.8, 'city': 1.1, 'dipl': 0.8, 'econ': 1.0, 'tech': 1.6},
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
    domain_weights={'unit': 0.8, 'city': 1.0, 'dipl': 1.6, 'econ': 1.0, 'tech': 0.9},
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

    def __init__(self, strategy: Optional[StrategyTemplate] = None,
                 max_candidates: int = 8):
        self.strategy = strategy or DEFENSIVE
        self.action_mapper = ActionOptionGenerator()
        # Cap on branches handed to DOF-Core per decision. The core's lookahead
        # cost grows roughly as max_candidates ** horizon, so a deeper horizon
        # needs a smaller shortlist.
        self.max_candidates = max_candidates

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

        return self._diverse_shortlist(prioritized, max_candidates=self.max_candidates)

    @staticmethod
    def _action_family(action: dict) -> tuple[str, str]:
        """(ctrl_type, action family) with parameter suffixes stripped.

        `goto_0` … `goto_300` are one kind of decision; `set_sci_lux_tax_0_40_60`
        is the family `set_sci_lux_tax`. Without this the shortlist fills with
        hundreds of variants of a single move and the agent never sees the other
        kinds of action available to it.
        """
        ctrl = action.get('ctrl_type', '')
        name = re.sub(r'(_\d+)+$', '', action.get('action_name', ''))
        return ctrl, name

    @classmethod
    def _diverse_shortlist(
        cls,
        ranked: list[dict],
        max_candidates: int = 8,
        top_by_gain: int = 4,
        top_reversible: int = 4,
    ) -> list[dict]:
        """Build a shortlist that spans distinct actions and keeps a safe branch.

        Ranking purely by projected gain produced shortlists made entirely of
        irreversible actions, which DOF-Core then vetoed (Axiom 4 penalty) —
        leaving the agent frozen even though reversible options existed. Ranking
        without deduplication produced shortlists of 300 near-identical moves.
        So: one representative per action family, best-gain kinds first, then the
        best reversible kinds as the veto's fallback.
        """
        def best_per_family(items: list[dict]) -> list[dict]:
            families: dict[tuple[str, str], dict] = {}
            for candidate in items:
                key = cls._action_family(candidate)
                current = families.get(key)
                if current is None or (
                        sum(candidate.get('projected_dof_delta', {}).values())
                        > sum(current.get('projected_dof_delta', {}).values())):
                    families[key] = candidate
            return list(families.values())

        picked: list[dict] = []
        seen: set[tuple[str, str]] = set()

        for candidate in best_per_family(ranked)[:top_by_gain]:
            key = cls._action_family(candidate)
            if key not in seen:
                seen.add(key)
                picked.append(candidate)

        reversible = [c for c in ranked if c.get('is_reversible', True)]
        for candidate in best_per_family(reversible)[:top_reversible]:
            key = cls._action_family(candidate)
            if key not in seen:
                seen.add(key)
                picked.append(candidate)

        return picked[:max_candidates]

    # ── scoring ──────────────────────────────────────────────────────────────

    @staticmethod
    def _domain_of(ctrl_type: str) -> str:
        if ctrl_type == 'unit':
            return 'unit'
        if ctrl_type == 'city':
            return 'city'
        if ctrl_type in ('dipl', 'diplomacy'):
            return 'dipl'
        if ctrl_type in ('gov', 'economy'):
            return 'econ'
        if ctrl_type == 'tech':
            return 'tech'
        return 'other'

    def weighted_dof_gain(self, candidate: dict) -> float:
        """Projected DoF gain, weighted by the strategy's domain preference.

        This is the primary objective: DOF-Core maximizes degrees of freedom.
        A strategy expresses itself through ``domain_weights`` rather than by
        overriding the objective, so every strategy still prefers the action
        that actually raises DoF within its valued domains.
        """
        raw = sum(candidate.get('projected_dof_delta', {}).values())
        domain = self._domain_of(candidate.get('ctrl_type', ''))
        weight = self.strategy.domain_weights.get(domain, 1.0)
        return raw * weight

    def _preference_score(self, candidate: dict) -> float:
        name = candidate.get('action_name', '')
        domain = self._domain_of(candidate.get('ctrl_type', ''))
        prefs = {
            'unit': self.strategy.preferred_unit_actions,
            'city': self.strategy.preferred_city_actions,
            'dipl': self.strategy.preferred_diplomacy_actions,
            'econ': self.strategy.preferred_economy_actions,
            'tech': self.strategy.preferred_tech_actions,
        }.get(domain, [])
        return float(sum(1 for pref in prefs if name.startswith(pref) or pref in name))

    def _prioritize(
        self,
        unit_actions: list[dict],
        city_actions: list[dict],
        dipl_actions: list[dict],
        econ_actions: list[dict],
        tech_actions: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Rank actions: projected DoF gain first, then strategy fit, then reversibility.

        Ordering by strategy fit before DoF was a real bug: hundreds of
        reversible `goto_*` actions outranked `build_city` (+0.3 DoF) and the
        highest-gain candidate never even reached the top-5 shortlist, so the
        agent spent whole games issuing DoF-neutral moves.
        """
        tech_actions = tech_actions or []
        all_actions = unit_actions + city_actions + dipl_actions + econ_actions + tech_actions

        all_actions.sort(
            key=lambda a: (
                self.weighted_dof_gain(a),
                self._preference_score(a),
                a.get('is_reversible', True),
            ),
            reverse=True,
        )

        return all_actions

    def select_best(
        self,
        candidates: list[dict[str, Any]],
        state: SystemStateMatrix,
    ) -> Optional[dict[str, Any]]:
        """Pick the candidate with the highest strategy-weighted DoF gain.

        Ties break towards reversible actions (DOF Axiom 4). Irreversibility is
        not banned here — that veto belongs to DOFCalculusCore — so an
        irreversible action is still taken when it is the only DoF-positive
        option.
        """
        if not candidates:
            return None

        return max(
            candidates,
            key=lambda c: (self.weighted_dof_gain(c), c.get('is_reversible', True)),
        )
