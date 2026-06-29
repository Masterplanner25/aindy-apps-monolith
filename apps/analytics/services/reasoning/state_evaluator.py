"""State evaluator — normalize raw orchestrator context into a StateSnapshot.

Aggregates KPI snapshot, feedback, memory signals, system state, goals, social
signals, and KPI thresholds into one normalized shape for the decision engine,
and derives a `kpi_health` view (which KPIs are below their low thresholds).
"""

from __future__ import annotations

from typing import Any

from apps.analytics.services.reasoning.types import StateSnapshot

# KPIs the decision engine thresholds on.
_KPI_FIELDS = ("execution_speed", "decision_efficiency", "focus_quality", "ai_productivity_boost")
_DEFAULT_KPI_LOW: dict[str, float] = {
    "execution_speed": 40.0,
    "decision_efficiency": 40.0,
    "focus_quality": 40.0,
    "ai_productivity_boost": 40.0,
}


def evaluate_state(
    score_snapshot: dict[str, Any] | None,
    *,
    feedback_context: dict[str, Any] | None = None,
    memory_signals: list[dict[str, Any]] | None = None,
    system_state: dict[str, Any] | None = None,
    goals: list[dict[str, Any]] | None = None,
    social_signals: list[dict[str, Any]] | None = None,
    kpi_low: dict[str, Any] | None = None,
) -> StateSnapshot:
    """Build a normalized :class:`StateSnapshot` from raw reasoning inputs."""
    feedback_context = dict(feedback_context or {})
    memory_signals = list(memory_signals or [])
    system_state = dict(system_state or {})
    goals = list(goals or [])
    social_signals = list(social_signals or [])
    kpi_low = dict(kpi_low or {})

    has_score = bool(score_snapshot)
    valid_score = False
    kpi_health: dict[str, dict[str, Any]] = {}
    if has_score:
        try:
            values = {field: float(score_snapshot.get(field, 50.0) or 50.0) for field in _KPI_FIELDS}
            valid_score = True
            for field, value in values.items():
                low = float(kpi_low.get(field, _DEFAULT_KPI_LOW[field]))
                kpi_health[field] = {"value": value, "low": low, "below": value < low}
        except (TypeError, ValueError):
            valid_score = False
            kpi_health = {}

    return StateSnapshot(
        score_snapshot=score_snapshot,
        feedback_context=feedback_context,
        memory_signals=memory_signals,
        system_state=system_state,
        goals=goals,
        social_signals=social_signals,
        kpi_low=kpi_low,
        has_score=has_score,
        valid_score=valid_score,
        kpi_health=kpi_health,
    )
