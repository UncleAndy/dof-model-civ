"""
The agent's model of the world, with a refinement loop.

Why this module exists
----------------------
The game hands over the *external world*: facts about entities that exist, tile
yields, legal actions, ruleset text. It never hands over a model of that world.
The agent needs one, and in this project that model is the table of
correspondences "external object ↔ DoF" (drafts/DOF_CALIBRATION.md §2–§9:
types, properties and limits, current/future split, the city and unit formulas,
thresholds, sinks, the source graph).

Until now that table lived as frozen constants in :mod:`env.config`, which means
**reality could not correct it**: the agent could see a contradiction and still
keep computing with the stale number. This module makes the model a piece of
agent *state*:

* **priors** — the pre-installed table (factory defaults from :mod:`env.config`);
* **provenance** — every entry records where it came from and how much it is
  trusted (`ruleset` > `measured` > `assumed`);
* **the world is primary** — when the world reports a value, the entry is
  corrected if the report is at least as trustworthy as the entry; otherwise the
  report is kept as evidence for statistical refinement (`pending`);
* **corrections are journaled and reversible** — nothing is silently rewritten.

Three kinds of knowledge, deliberately handled differently:

1. **Ruleset facts** (unit type parameters, `granary_size = 10 × (size + 1)`,
   `city_radius_sq`) — the world publishes them, so they are *directly*
   correctable: `observe(..., source=RULESET)`.
2. **Coefficients** of our own formulas (`CITY_M1_FOOD`, `W_FUTURE_UNIT`, …) —
   the world cannot publish them (there are no city *types* in the observation,
   only instances), so they are only ever refined statistically from accumulated
   prediction/observation pairs, never from a single sighting.
3. **Instance facts** (a city's size, a unit's health) — NOT model knowledge at
   all. They are state and must always be read from the world; the model only
   supplies how to interpret them. Confusing the two is what made the bridge
   estimate a not-yet-founded city from an already-existing one.

RESTORED 2026-09-27: this file was overwritten by accident (a new "measured
facts" store was written under the same name) and rebuilt from its own bytecode
(`env/__pycache__/world_model.cpython-312.pyc`, 2026-09-26 20:09) plus the test
suite that pins its behaviour (`tests/unit/test_world_model.py`,
`test_experiments.py`, `test_false_claim.py`). The measurements, verdicts,
provenance rules and revision journal are as documented above.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Optional

from . import config as cfg

#: Метка заведомо неверного утверждения (см. `plant_false_claim`).
FALSE_CLAIM_MARKER = 'ЗАВЕДОМО НЕВЕРНОЕ УТВЕРЖДЕНИЕ'


class Provenance(Enum):
    """Where a model entry came from — and therefore what may overwrite it."""

    ASSUMED = 'assumed'
    MEASURED = 'measured'
    RULESET = 'ruleset'


#: Ранг источника: чем больше, тем сильнее его слово против записи модели.
STRENGTH: dict[Provenance, int] = {
    Provenance.ASSUMED: 1,
    Provenance.MEASURED: 2,
    Provenance.RULESET: 3,
}


@dataclass
class ModelEntry:
    """One piece of the agent's world model, with its provenance."""

    key: str
    value: Any
    source: Provenance = Provenance.ASSUMED
    confidence: float = 0.5
    verified_turn: Optional[int] = None
    evidence: str = ''
    revision: int = 0
    history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'key': self.key,
            'value': self.value,
            'source': self.source.value,
            'confidence': self.confidence,
            'verified_turn': self.verified_turn,
            'revision': self.revision,
            'evidence': self.evidence,
        }


@dataclass
class Reconciliation:
    """What the world reported about one key, and what the model did about it."""

    key: str
    prior: Any
    observed: Any
    verdict: str
    turn: int = 0
    source: Provenance = Provenance.RULESET
    evidence: str = ''

    def to_dict(self) -> dict:
        return {
            'key': self.key,
            'prior': self.prior,
            'observed': self.observed,
            'verdict': self.verdict,
            'turn': self.turn,
            'source': self.source.value,
            'value': self.observed if self.verdict in ('new', 'match', 'corrected')
            else self.prior,
            'evidence': self.evidence,
        }


#: Facts the world itself publishes. `rules.*` and the granary/radius/citizen
#: rules come from `obs['rules']`; the hp of the unit types from the unit specs.
RULESET_PRIORS: dict[str, Any] = {
    'city.granary_per_size': 10.0,
    'city.radius_sq': 5.0,
    'tech.nominal_turns': cfg.TECH_NOMINAL_TURNS,
    'rules.citymindist': 2.0,
    'rules.celebratesize': 3.0,
    'rules.angrycitizen': 1.0,
    'rules.food_cost': cfg.FOOD_COST,
    'rules.border_city_radius_sq': 17.0,
    'rules.foodbox': 100.0,
    'rules.add_to_size_limit': 8.0,
    #: Предел роста города по правилам мира: `add_to_size_limit = 8` в наборе правил
    #: с комментарием «cities >= this cannot be added to» — город такого размера не
    #: растёт от запаса еды. Взято из `cities.ruleset` (не выдумано).
    'city.growth_base_limit': 8.0,
    'rules.base_tech_cost': 20.0,
}

#: Derived from the factory table: hit points per unit type name.
DERIVED_RULESET_PRIORS: dict[str, Any] = {
    f'unit_type.{name}.hp': float(hp)
    for name, hp in getattr(cfg, 'UNIT_MAX_HP_BY_TYPE', {}).items()
}

#: Coefficients of our own formulas: the world cannot publish them, so they
#: start as assumptions and are only ever refined from accumulated evidence.
ASSUMED_PRIORS: dict[str, Any] = {
    'DOF_SCALE': cfg.DOF_SCALE,
    'CITY_CEIL': cfg.CITY_CEIL,
    'CORE_DOF_SCALE': cfg.CORE_DOF_SCALE,
    'AXIOM4_PENALTY_OPTIONS': cfg.AXIOM4_PENALTY_OPTIONS,
    'UNIT_EXISTENCE_W': cfg.UNIT_EXISTENCE_W,
    'UNIT_HEALTH_W': cfg.UNIT_HEALTH_W,
    'UNIT_ATTACK_W': cfg.UNIT_ATTACK_W,
    'UNIT_ATTACK_REF': cfg.UNIT_ATTACK_REF,
    'UNIT_DEFENSE_W': cfg.UNIT_DEFENSE_W,
    'UNIT_DEFENSE_REF': cfg.UNIT_DEFENSE_REF,
    'UNIT_FIREPOWER_W': cfg.UNIT_FIREPOWER_W,
    'UNIT_FIREPOWER_REF': cfg.UNIT_FIREPOWER_REF,
    'UNIT_MOVE_W': cfg.UNIT_MOVE_W,
    'UNIT_MOVE_REF': cfg.UNIT_MOVE_REF,
    'UNIT_VISION_W': cfg.UNIT_VISION_W,
    'UNIT_VISION_REF': cfg.UNIT_VISION_REF,
    'UNIT_VETERAN_W': cfg.UNIT_VETERAN_W,
    'UNIT_VETERAN_REF': cfg.UNIT_VETERAN_REF,
    'UNIT_CURRENT_CAP': cfg.UNIT_CURRENT_CAP,
    'UNIT_FUTURE_SETTLE_W': cfg.UNIT_FUTURE_SETTLE_W,
    'UNIT_FUTURE_WORKER_W': cfg.UNIT_FUTURE_WORKER_W,
    'UNIT_FUTURE_CONVERT_W': cfg.UNIT_FUTURE_CONVERT_W,
    'UNIT_FUTURE_TRANSPORT_W': cfg.UNIT_FUTURE_TRANSPORT_W,
    'W_FUTURE_UNIT': cfg.W_FUTURE_UNIT,
    'CARRIER_DECAY_PER_TURN': cfg.CARRIER_DECAY_PER_TURN,
    'CARRIER_DECAY_FLOOR': cfg.CARRIER_DECAY_FLOOR,
    'UNDEPLOYED_CARRIER_SINK_PER_TURN': cfg.UNDEPLOYED_CARRIER_SINK_PER_TURN,
    'W_GROWTH': cfg.W_GROWTH,
    'GROWTH_HORIZON_TURNS': cfg.GROWTH_HORIZON_TURNS,
    'FOOD_COST': cfg.FOOD_COST,
    'SITE_MIN_FOOD': cfg.SITE_MIN_FOOD,
    'SITE_MIN_FOOD_FIRST': cfg.SITE_MIN_FOOD_FIRST,
    'SITE_MIN_FOOD_FIRST_DECAY': cfg.SITE_MIN_FOOD_FIRST_DECAY,
    'SITE_MIN_FOOD_FIRST_FLOOR': cfg.SITE_MIN_FOOD_FIRST_FLOOR,
    'UNKNOWN_FILL_FOOD': cfg.UNKNOWN_FILL_FOOD,
    'UNKNOWN_FILL_SHIELDS': cfg.UNKNOWN_FILL_SHIELDS,
    'UNKNOWN_FILL_TRADE': cfg.UNKNOWN_FILL_TRADE,
    'UNKNOWN_BEST_FOOD': cfg.UNKNOWN_BEST_FOOD,
    'UNKNOWN_BEST_SHIELDS': cfg.UNKNOWN_BEST_SHIELDS,
    'UNKNOWN_BEST_TRADE': cfg.UNKNOWN_BEST_TRADE,
    'INFO_GAP_FLOOR_OPTIONS': cfg.INFO_GAP_FLOOR_OPTIONS,
    'SITE_GATE_SIZE': cfg.SITE_GATE_SIZE,
    'SITE_COAST_BONUS': cfg.SITE_COAST_BONUS,
    'SITE_RESOURCE_BONUS': cfg.SITE_RESOURCE_BONUS,
    'SITE_OPTION_BONUS_CAP': cfg.SITE_OPTION_BONUS_CAP,
    'WATER_TERRAINS': tuple(cfg.WATER_TERRAINS),
    'MEASURED_EXTRA_EFFECTS': dict(cfg.MEASURED_EXTRA_EFFECTS),
    'POP_CARRIER_COUNTS_HEALTH_IN_CURRENT': cfg.POP_CARRIER_COUNTS_HEALTH_IN_CURRENT,
    'CITY_BASE': cfg.CITY_BASE,
    'CITY_POP': cfg.CITY_POP,
    'CITY_CAP_M1': cfg.CITY_CAP_M1,
    'CITY_CAP_M2': cfg.CITY_CAP_M2,
    'CITY_M1_FOOD': cfg.CITY_M1_FOOD,
    'CITY_M1_GRANARY': cfg.CITY_M1_GRANARY,
    'CITY_M1_IMPROV': cfg.CITY_M1_IMPROV,
    'IMPROVEMENT_BUILD_BONUS': cfg.IMPROVEMENT_BUILD_BONUS,
    'IMPROVEMENT_SHIELD_RATE': cfg.IMPROVEMENT_SHIELD_RATE,
    'IMPROVEMENT_HORIZON_TURNS': cfg.IMPROVEMENT_HORIZON_TURNS,
    'CITY_TILE_FAMILY': cfg.CITY_TILE_FAMILY,
    'CITY_TILE_PAIR': cfg.CITY_TILE_PAIR,
    'CITY_M2_SHIELD': cfg.CITY_M2_SHIELD,
    'CITY_M2_TRADE': cfg.CITY_M2_TRADE,
    'CITY_M2_GOLD': cfg.CITY_M2_GOLD,
    'CITY_M2_SCIENCE': cfg.CITY_M2_SCIENCE,
    'CITY_M2_LUXURY': cfg.CITY_M2_LUXURY,
    'CITY_CORRUPTION_W': cfg.CITY_CORRUPTION_W,
    'CITY_HAPPY_W': cfg.CITY_HAPPY_W,
    'CITY_UNHAPPY_W': cfg.CITY_UNHAPPY_W,
    'CITY_ANGRY_W': cfg.CITY_ANGRY_W,
    'GARRISON_W': cfg.GARRISON_W,
    'UNIT_UPKEEP_SINK_W': cfg.UNIT_UPKEEP_SINK_W,
    'TECH_BASE_OPTIONS': cfg.TECH_BASE_OPTIONS,
}

#: How many confirmations it takes for confidence to reach 0.5.
CONFIDENCE_K: int = 3


class WorldModel:
    """The agent's model of the world: entries, provenance, refinement loop."""

    def __init__(self, ruleset_priors: Optional[Mapping[str, Any]] = None,
                 assumed_priors: Optional[Mapping[str, Any]] = None,
                 min_stat_n: int = 5, min_relative_change: float = 0.01,
                 tol: float = 1e-9) -> None:
        self.entries: dict[str, ModelEntry] = {}
        self.reconciliations: list[Reconciliation] = []
        #: key → [(turn, predicted, observed)] — evidence for coefficient fits.
        self.pairs: dict[str, list[tuple[int, float, float]]] = {}
        #: key → how many times the world confirmed it (matches + corrections).
        self.corroborations: dict[str, int] = {}
        #: action family → how many times the agent tried it unmeasured.
        self.experiment_attempts: dict[str, int] = {}
        self.min_stat_n = int(min_stat_n)
        self.min_relative_change = float(min_relative_change)
        self.tol = float(tol)

        for key, value in (RULESET_PRIORS if ruleset_priors is None
                           else ruleset_priors).items():
            self.entries[key] = ModelEntry(key=key, value=value,
                                           source=Provenance.RULESET,
                                           confidence=0.9)
        for key, value in DERIVED_RULESET_PRIORS.items():
            self.entries.setdefault(key, ModelEntry(key=key, value=value,
                                                    source=Provenance.RULESET,
                                                    confidence=0.7))
        for key, value in (ASSUMED_PRIORS if assumed_priors is None
                           else assumed_priors).items():
            self.entries.setdefault(key, ModelEntry(key=key, value=value,
                                                    source=Provenance.ASSUMED,
                                                    confidence=0.5))
        self._values_cache: Optional[dict[str, Any]] = None

    # ── construction ────────────────────────────────────────────────────────
    @classmethod
    def from_config(cls) -> 'WorldModel':
        """The pre-installed model: factory defaults out of :mod:`env.config`."""
        return cls()

    # ── reading ─────────────────────────────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        entry = self.entries.get(key)
        return default if entry is None else entry.value

    def values(self) -> dict[str, Any]:
        """All values as a flat dict, for the formula functions.

        Cached: the formulas read several keys per entity and this is on the hot
        path. Every correction invalidates the cache.
        """
        if self._values_cache is None:
            self._values_cache = {k: e.value for k, e in self.entries.items()}
        return self._values_cache

    def __getitem__(self, key: str) -> Any:
        return self.entries[key].value

    def source_of(self, key: str) -> Optional[Provenance]:
        entry = self.entries.get(key)
        return None if entry is None else entry.source

    # ── the refinement loop ─────────────────────────────────────────────────
    def observe(self, key: str, observed: Any, turn: int,
                source: Provenance = Provenance.RULESET, evidence: str = '',
                tol: Optional[float] = None) -> Reconciliation:
        """Report a fact from the world about one model key.

        The verdict is one of:

        * ``new``       — the model had no entry; it is registered with the
          report's provenance.
        * ``match``     — the entry already says this; its verification turn is
          refreshed (the model is confirmed against the world).
        * ``corrected`` — the entry was wrong and the report is at least as
          trustworthy as the entry. The old value goes into the entry's history
          (so the change is auditable and reversible) and the cached values are
          invalidated.
        * ``pending``   — the report disagrees but is *less* trustworthy than the
          entry (an assumption cannot overwrite a measurement, and two
          assumptions never overwrite each other). Kept as evidence for a later
          statistical refinement.
        """
        tol = self.tol if tol is None else float(tol)
        entry = self.entries.get(key)
        if entry is None:
            self.entries[key] = ModelEntry(key=key, value=observed, source=source,
                                           confidence=0.5, verified_turn=turn,
                                           evidence=evidence)
            self._values_cache = None
            rec = Reconciliation(key=key, prior=None, observed=observed,
                                 verdict='new', turn=turn, source=source,
                                 evidence=evidence)
        elif _equal(entry.value, observed, tol):
            entry.verified_turn = turn
            self._confirm(key)
            rec = Reconciliation(key=key, prior=entry.value, observed=observed,
                                 verdict='match', turn=turn, source=source,
                                 evidence=evidence)
        elif _may_correct(source, entry.source):
            old = entry.value
            entry.history.append({'old': old, 'new': observed, 'turn': turn,
                                  'source': source.value, 'evidence': evidence})
            entry.value = observed
            entry.source = source
            entry.revision += 1
            entry.verified_turn = turn
            entry.evidence = evidence
            self._confirm(key)
            self._values_cache = None
            rec = Reconciliation(key=key, prior=old, observed=observed,
                                 verdict='corrected', turn=turn, source=source,
                                 evidence=evidence)
        else:
            rec = Reconciliation(key=key, prior=entry.value, observed=observed,
                                 verdict='pending', turn=turn, source=source,
                                 evidence=evidence)
        return self._record(rec)

    def _confirm(self, key: str) -> None:
        self.corroborations[key] = self.corroborations.get(key, 0) + 1

    def _record(self, rec: Reconciliation) -> Reconciliation:
        self.reconciliations.append(rec)
        return rec

    def plant_false_claim(self, key: str, value: Any, note: str = '') -> None:
        """Заведомо неверное утверждение — чтобы проверить, что мир его исправит.

        Нужно ровно за одним: Axiom «реальность первична» до сих пор проверялся
        только тестами, то есть тем, что мы сами придумали. Живой мир, как
        выяснилось, почти не спорит — он **дополняет** (126 сверок: 96 совпало,
        30 новых, 0 исправлений). Значит, ветку исправления надо вызвать
        намеренно: положить неверное значение с САМЫМ сильным провенансом, чтобы
        мир мог его исправить только если правило «равный ранг исправляет» и
        правда работает на живых данных.

        Evidence помечается явно, чтобы такой факт нельзя было принять за
        измерение: он не должен попасть в отчёт как знание о мире.
        """
        evidence = FALSE_CLAIM_MARKER if not note else f'{FALSE_CLAIM_MARKER}: {note}'
        self.entries[key] = ModelEntry(key=key, value=value,
                                       source=Provenance.RULESET, confidence=0.9,
                                       evidence=evidence)
        self._values_cache = None

    def confidence(self, key: str, n: Optional[int] = None) -> float:
        """How well the world has confirmed a key: `n / (n + CONFIDENCE_K)`.

        0.0 — never confirmed (a pure assumption, or a key we only just claimed);
        0.5 — confirmed `CONFIDENCE_K` times; asymptotically 1.0. Used to price the
        value of finding out: the less we know, the more an experiment is worth.
        """
        count = self.corroborations.get(key, 0) if n is None else int(n)
        return float(count) / float(count + CONFIDENCE_K)

    def unknowns(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Keys the model merely *assumes* — the visible list of our ignorance.

        A key qualifies when nothing from the world has ever confirmed it (zero
        corroborations). This is what makes silence visible: an unmeasured quantity
        is reported here instead of quietly contributing a plausible number.
        """
        out = [{
            'key': key,
            'value': entry.value,
            'source': entry.source.value,
            'confidence': self.confidence(key),
            'evidence': entry.evidence,
        } for key, entry in self.entries.items()
            if self.corroborations.get(key, 0) == 0]
        out.sort(key=lambda item: item['key'])
        return out if limit is None else out[:int(limit)]

    def pending_count(self, key: str) -> int:
        """How many times a report disagreed but was not trustworthy enough to win."""
        return sum(1 for r in self.reconciliations
                   if r.key == key and r.verdict == 'pending')

    def contested(self, min_reports: int = 3) -> list[dict[str, Any]]:
        """Keys the world keeps arguing about — questions the model must settle.

        A key lands here when at least `min_reports` reports disagreed with the
        entry without being allowed to correct it (a weaker source, or two
        assumptions). Those reports are evidence; this method is their consumer,
        so accumulated disagreement stops being ballast and becomes a task.
        """
        out: list[dict[str, Any]] = []
        for rec in self.reconciliations:
            if rec.verdict != 'pending':
                continue
            reports = self.pending_count(rec.key)
            if reports < int(min_reports):
                continue
            if any(item['key'] == rec.key for item in out):
                continue
            entry = self.entries.get(rec.key)
            out.append({'key': rec.key,
                        'value': None if entry is None else entry.value,
                        'observed': rec.observed,
                        'reports': reports,
                        'source': rec.source.value,
                        'evidence': rec.evidence})
        out.sort(key=lambda item: (-item['reports'], item['key']))
        return out

    # ── experiments ─────────────────────────────────────────────────────────
    def record_experiment(self, family: str, turn: int) -> int:
        """Note that the agent tried an action family it had never measured.

        Counting attempts is what turns "unknown forever" into "getting known":
        each attempt raises the family's confidence, so the incentive to probe a
        given family decays as it is probed instead of paying forever.
        """
        count = self.experiment_attempts.get(family, 0) + 1
        self.experiment_attempts[family] = count
        self._record(Reconciliation(key=f'experiment.{family}', prior=count - 1,
                                    observed=count, verdict='experiment',
                                    turn=turn, source=Provenance.MEASURED))
        return count

    def experiment_confidence(self, family: str, n: Optional[int] = None) -> float:
        """Confidence in an action family, from attempts: `n / (n + CONFIDENCE_K)`."""
        count = self.experiment_attempts.get(family, 0) if n is None else int(n)
        return float(count) / float(count + CONFIDENCE_K)

    # ── coefficient refinement ──────────────────────────────────────────────
    def record_pair(self, key: str, predicted: float, observed: float,
                    turn: int) -> None:
        """Store a (predicted, observed) pair for a coefficient key.

        Coefficients of our own formulas are not published by the game, so the
        only route to improving them is accumulating how well they predicted
        something that *is* observable. Until such a criterion exists for a key,
        its pairs simply accumulate — they are never turned into a silent change.
        """
        self.pairs.setdefault(key, []).append((int(turn), float(predicted),
                                               float(observed)))

    def stat_pairs(self, key: str) -> int:
        return len(self.pairs.get(key) or [])

    def refine_coefficient(self, key: str,
                           min_n: Optional[int] = None) -> Optional[float]:
        """Fit a coefficient to its accumulated pairs, if there are enough.

        The fit is multiplicative: ``new = prior × mean(observed / predicted)``,
        applied only when at least ``min_n`` pairs exist and the change exceeds
        ``min_relative_change``. It is a *fit*, not a fact, and it is journaled
        with source ``measured`` so that a later ruleset read can still override
        it. Returns the new value, or None when nothing was changed.
        """
        need = self.min_stat_n if min_n is None else int(min_n)
        pairs = self.pairs.get(key) or []
        if len(pairs) < need:
            return None
        ratios = [observed / predicted for _turn, predicted, observed in pairs
                  if predicted]
        if not ratios:
            return None
        factor = sum(ratios) / len(ratios)
        prior = self.get(key)
        try:
            candidate = float(prior) * factor
        except (TypeError, ValueError):
            return None
        if prior and abs(candidate - float(prior)) <= (
                self.min_relative_change * abs(float(prior))):
            return None
        entry = self.entries.get(key)
        if entry is None:
            return None
        entry.history.append({'old': entry.value, 'new': candidate,
                              'turn': int(pairs[-1][0]),
                              'source': Provenance.MEASURED.value,
                              'evidence': f'fit over {len(pairs)} pairs'})
        entry.value = candidate
        entry.source = Provenance.MEASURED
        entry.revision += 1
        self._values_cache = None
        return candidate

    # ── audit ───────────────────────────────────────────────────────────────
    def corrections(self) -> list[ModelEntry]:
        """Entries reality has actually corrected (for the report)."""
        return [e for e in self.entries.values() if e.revision > 0]

    def revert(self, key: str) -> bool:
        """Undo the last correction of ``key`` (corrections must be reversible)."""
        entry = self.entries.get(key)
        if entry is None or not entry.history:
            return False
        last = entry.history.pop()
        entry.value = last['old']
        entry.revision = max(0, entry.revision - 1)
        source = last.get('source')
        for candidate in Provenance:
            if candidate.value == source:
                entry.source = candidate
                break
        if not entry.history:
            entry.evidence = ''
        self._values_cache = None
        return True

    def summary(self) -> dict[str, Any]:
        by_verdict: dict[str, int] = {}
        for rec in self.reconciliations:
            by_verdict[rec.verdict] = by_verdict.get(rec.verdict, 0) + 1
        by_source: dict[str, int] = {}
        for entry in self.entries.values():
            by_source[entry.source.value] = by_source.get(entry.source.value, 0) + 1
        return {
            'verdicts': by_verdict,
            'corrections': len(self.corrections()),
            'entries': len(self.entries),
            'entries_by_source': by_source,
            'pairs': {k: len(v) for k, v in self.pairs.items()},
            'unknowns': len(self.unknowns()),
            'confidence_k': CONFIDENCE_K,
        }

    def mismatches(self) -> Iterable[Reconciliation]:
        """Reconiliations where the world and the model disagreed (audit trail)."""
        return [r for r in self.reconciliations
                if r.verdict in ('corrected', 'pending')]

    def to_dict(self) -> dict:
        return {
            'entries': [e.to_dict() for e in self.entries.values()],
            'reconciliations': [r.to_dict() for r in self.reconciliations],
            'pairs': {k: list(v) for k, v in self.pairs.items()},
            'corroborations': dict(self.corroborations),
            'experiment_attempts': dict(self.experiment_attempts),
        }


def _may_correct(report: Provenance, entry: Provenance) -> bool:
    """May a report of rank ``report`` overwrite an entry of rank ``entry``?

    A stronger report always may. A report of *equal* strength may too — a new
    measurement supersedes an old one, and a new ruleset read supersedes a stale
    one — with one deliberate exception: **an assumption never overwrites an
    assumption.** Two guesses disagreeing is not evidence about the world, it is
    just two guesses; the report is kept as evidence (`pending`) instead.
    """
    if report is Provenance.ASSUMED and entry is Provenance.ASSUMED:
        return False
    return STRENGTH[report] >= STRENGTH[entry]


def _equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    """Равны ли значения: числа — с допуском, прочее — как есть."""
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=float(tol))
    try:
        return bool(a == b)
    except Exception:  # noqa: BLE001
        return False


#: Модель по умолчанию для свободных функций (скрипты, тесты). Решение
#: принимает модель агента, а не эта.
_DEFAULT: Optional[WorldModel] = None


def default_model() -> WorldModel:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = WorldModel.from_config()
    return _DEFAULT
