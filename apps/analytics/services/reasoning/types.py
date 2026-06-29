"""Normalized reasoning contracts shared across the reasoning engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StateSnapshot:
    """A normalized snapshot of the inputs a reasoning decision is made from.

    Produced by the state evaluator from raw orchestrator context so the
    decision engine consumes one stable shape. ``kpi_health`` is a derived,
    observability-friendly view of which KPIs are below their low thresholds.
    """

    score_snapshot: dict[str, Any] | None
    feedback_context: dict[str, Any]
    memory_signals: list[dict[str, Any]]
    system_state: dict[str, Any]
    goals: list[dict[str, Any]]
    social_signals: list[dict[str, Any]]
    kpi_low: dict[str, Any]
    has_score: bool
    valid_score: bool
    kpi_health: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class ReasoningResult:
    """The normalized output of a reasoning decision.

    Wraps the chosen ``decision_type`` and the decision ``payload`` (which carries
    ``reason``, ``next_action``, and the weighting annotations). ``to_tuple()``
    preserves the legacy ``(decision_type, payload)`` shape callers expect.
    """

    decision_type: str
    payload: dict[str, Any]

    @property
    def reason(self) -> str | None:
        return self.payload.get("reason")

    @property
    def next_action(self) -> dict[str, Any] | None:
        return self.payload.get("next_action")

    @property
    def suggested_goal(self) -> Any:
        return self.payload.get("suggested_goal")

    def to_tuple(self) -> tuple[str, dict[str, Any]]:
        return self.decision_type, self.payload

    def as_dict(self) -> dict[str, Any]:
        return {"decision_type": self.decision_type, **self.payload}
