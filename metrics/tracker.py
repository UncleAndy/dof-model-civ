"""
Unified match metrics for DOF-MODEL-CIV.

Every agent class in a tournament (random, no-op, DOF strategies) is measured
through the same recorder, so comparisons are apples-to-apples:

* the DoF index and entity count come from the same extractor call,
* an irreversible action is classified with the same
  :func:`env.action_mapper.classify_reversibility` rule regardless of which
  agent produced it,
* a turn with no action (no-op, or nothing valid available) is recorded as a
  *skipped* turn instead of silently counting as an irreversible-free action.

Before this module the irreversibility ratio was only instrumented inside the
DOF agent, which made the random baseline look like it never acted
irreversibly. That was a measurement artefact, not a result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from env.action_mapper import classify_reversibility


@dataclass
class StepRecord:
    """One decision step of a match."""
    turn: int
    dof_index: float
    entity_count: int
    action: Optional[tuple[str, Any, str]] = None
    is_reversible: Optional[bool] = None
    skipped: bool = False
    total_dof_index: Optional[float] = None


@dataclass
class MatchMetrics:
    """Accumulates per-turn records and per-decision accounting of one match.

    Two levels are kept deliberately separate:

    * ``steps`` — one record per **game turn** (DoF index, entity count). This is
      the unit of comparison between agents.
    * ``decisions`` — one record per action actually handed to ``env.step``.
      Reversibility lives here, because a turn may contain several decisions and
      a no-op turn contains none.
    """

    agent_name: str = ""
    seed: Optional[int] = None
    engine: str = ""
    steps: list[StepRecord] = field(default_factory=list)
    decisions: list[StepRecord] = field(default_factory=list)
    error: str = ""
    finished: bool = False
    include_series: bool = False
    #: Какой выбор заклинил стенд (действие, о которое step не вернулся). Не
    #: ошибка кода, а измерение: этот матч потерян, но знание остаётся.
    wedge_action: Optional[dict] = None
    #: Включена ли надбавка за незнание в этом матче (для A/B-прогона).
    curiosity: bool = True
    #: Прирост знания за матч: попытки-эксперименты и пары «прогноз↔факт».
    experiments_total: int = 0
    pairs_total: int = 0
    #: По семействам: что именно агент пробовал. Без этого «18 проб» ничего не
    #: говорит о том, куда ушло любопытство.
    experiment_families: dict[str, int] = field(default_factory=dict)
    #: Слот, на котором игрался матч. Разные слоты — разные карты, поэтому без
    #: него A/B «с любопытством / без» нельзя сопоставить по одной и той же среде.
    port: Optional[int] = None
    #: Отпечаток старта: где мы появились и что видно с этой точки. Каждый матч —
    #: своя среда (измерено: три прогона на одном слоте дали три разных старта),
    #: поэтому «пара по слоту» не существует — отпечаток нужен, чтобы это видеть,
    #: а не предполагать.
    start_fingerprint: str = ""
    #: Сколько клеток разведано на 1-м ходу — мера слепоты старта.
    revealed_cells: int = 0
    #: Центр разведанной области (старт), если определился.
    start_xy: Optional[list] = None
    #: Сколько сверок модели с миром дали каждый вердикт.
    reconciled: dict[str, int] = field(default_factory=dict)
    #: Ключи, которые мир фактически исправил, — прямое свидетельство Axiom
    #: «реальность первична» на живых данных.
    corrected_keys: list[str] = field(default_factory=list)
    #: Заведомо неверные утверждения, внедрённые перед матчем (проверка коррекции).
    false_claims: list[str] = field(default_factory=list)
    #: Журнал исправлений: что именно мир поправил, когда и с какого значения.
    #: Счётчик «corrected: 6» без журнала — это цифра, которой нельзя доверять:
    #: по ней не видно, шесть разных ключей исправлено или один шесть раз.
    correction_log: list[dict] = field(default_factory=list)

    def _series_payload(self) -> dict[str, Any]:
        if not self.include_series:
            return {}
        return {
            "turns_series": [s.turn for s in self.steps],
            "dof_series": self.dof_series,
            "total_dof_series": self.total_dof_series,
            "entity_series": self.entity_series,
            "decisions_per_turn": self.decisions_per_turn,
            "decisions": [
                None if d.action is None else [d.action[0], d.action[1], d.action[2]]
                for d in self.decisions
            ],
            "decision_turns": [d.turn for d in self.decisions],
            "reversible_series": [d.is_reversible for d in self.decisions],
        }

    # ── recording ────────────────────────────────────────────────────────────

    def record_step(
        self,
        turn: int,
        dof_index: float,
        entity_count: int,
        action: Optional[tuple[str, Any, str]],
        total_dof_index: Optional[float] = None,
    ) -> StepRecord:
        """Record one decision step.

        ``action`` is the tuple handed to ``env.step`` (``None`` when the agent
        declined to act). Reversibility is derived from the action *name* only,
        so it is defined for every agent identically.

        ``dof_index`` is the mean DoF over non-collapse entities (an intuitive
        summary); ``total_dof_index`` is the DOF-SPEC index ``Σ ln(DoF(e))`` over
        the calculation set, which is the quantity the spec orders decisions by.
        """
        if action is None:
            record = StepRecord(
                turn=turn,
                dof_index=dof_index,
                entity_count=entity_count,
                action=None,
                is_reversible=None,
                skipped=True,
                total_dof_index=total_dof_index,
            )
        else:
            action_name = action[2] if len(action) > 2 else ""
            record = StepRecord(
                turn=turn,
                dof_index=dof_index,
                entity_count=entity_count,
                action=action,
                is_reversible=classify_reversibility(action_name),
                skipped=False,
                total_dof_index=total_dof_index,
            )

        self.steps.append(record)
        if action is not None:
            self.record_decision(turn, action)
        return record

    def record_decision(
        self,
        turn: int,
        action: tuple[str, Any, str],
    ) -> StepRecord:
        """Record one action actually handed to the environment."""
        action_name = action[2] if len(action) > 2 else ""
        record = StepRecord(
            turn=turn,
            dof_index=0.0,
            entity_count=0,
            action=action,
            is_reversible=classify_reversibility(action_name),
            skipped=False,
        )
        self.decisions.append(record)
        return record

    # ── aggregates ───────────────────────────────────────────────────────────

    @property
    def turns_played(self) -> int:
        return len(self.steps)

    @property
    def actions_issued(self) -> int:
        return len(self.decisions)

    @property
    def skipped_turns(self) -> int:
        """Turns in which the agent issued no decision at all."""
        acted_turns = {d.turn for d in self.decisions}
        return sum(1 for s in self.steps if s.turn not in acted_turns)

    @property
    def decisions_per_turn(self) -> list[int]:
        counts: dict[int, int] = {}
        for d in self.decisions:
            counts[d.turn] = counts.get(d.turn, 0) + 1
        return [counts.get(s.turn, 0) for s in self.steps]

    @property
    def irreversible_actions(self) -> int:
        return sum(1 for d in self.decisions if d.is_reversible is False)

    @property
    def irreversibility_ratio(self) -> float:
        """Share of *issued* actions that are irreversible.

        Skipped turns are excluded from the denominator; ``actions_issued`` and
        ``skipped_turns`` are reported alongside so the ratio can never be read
        as "did nothing therefore safe".
        """
        issued = self.actions_issued
        return self.irreversible_actions / issued if issued else 0.0

    @property
    def dof_series(self) -> list[float]:
        return [s.dof_index for s in self.steps]

    @property
    def total_dof_series(self) -> list[float]:
        return [s.total_dof_index for s in self.steps if s.total_dof_index is not None]

    @property
    def avg_total_dof_index(self) -> float:
        """Mean DOF-SPEC index Σ ln(DoF(e)) over the match."""
        series = self.total_dof_series
        return sum(series) / len(series) if series else 0.0

    @property
    def final_total_dof_index(self) -> float:
        series = self.total_dof_series
        return series[-1] if series else 0.0

    @property
    def entity_series(self) -> list[int]:
        return [s.entity_count for s in self.steps]

    @property
    def avg_dof(self) -> float:
        series = self.dof_series
        return sum(series) / len(series) if series else 0.0

    @property
    def final_dof(self) -> float:
        return self.dof_series[-1] if self.steps else 0.0

    @property
    def min_ent(self) -> int:
        series = self.entity_series
        return min(series) if series else 0

    @property
    def max_ent(self) -> int:
        series = self.entity_series
        return max(series) if series else 0

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "agent": self.agent_name,
            "seed": self.seed,
            "engine": self.engine,
            "turns": self.turns_played,
            "avg_dof": self.avg_dof,
            "final_dof": self.final_dof,
            "avg_total_dof_index": self.avg_total_dof_index,
            "final_total_dof_index": self.final_total_dof_index,
            "min_entities": self.min_ent,
            "max_entities": self.max_ent,
            "actions_issued": self.actions_issued,
            "decisions_per_turn_mean": (
                sum(self.decisions_per_turn) / len(self.decisions_per_turn)
                if self.decisions_per_turn else 0.0
            ),
            "skipped_turns": self.skipped_turns,
            "irreversible_actions": self.irreversible_actions,
            "irreversibility_ratio": self.irreversibility_ratio,
            "error": self.error,
            "wedge_action": self.wedge_action,
            "curiosity": self.curiosity,
            "experiments_total": self.experiments_total,
            "pairs_total": self.pairs_total,
            "experiment_families": self.experiment_families,
            "port": self.port,
            "start_fingerprint": self.start_fingerprint,
            "revealed_cells": self.revealed_cells,
            "start_xy": self.start_xy,
            "reconciled": self.reconciled,
            "corrected_keys": self.corrected_keys,
            "false_claims": self.false_claims,
            "correction_log": self.correction_log,
        }
        payload.update(self._series_payload())
        return payload


def agent_turns(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a list of per-episode metric dicts for one agent."""
    n = len(records)
    if n == 0:
        return {"n": 0}

    def mean(key: str) -> float:
        return sum(r.get(key, 0.0) or 0.0 for r in records) / n

    return {
        "n": n,
        "avg_dof": mean("avg_dof"),
        "final_dof": mean("final_dof"),
        "avg_total_dof_index": mean("avg_total_dof_index"),
        "final_total_dof_index": mean("final_total_dof_index"),
        "irreversibility_ratio": mean("irreversibility_ratio"),
        "turns": mean("turns"),
        "actions_issued": mean("actions_issued"),
        "skipped_turns": mean("skipped_turns"),
        "errors": sum(1 for r in records if r.get("error")),
    }