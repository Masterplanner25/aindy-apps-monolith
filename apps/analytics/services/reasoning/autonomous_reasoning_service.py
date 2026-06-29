"""Autonomous reasoning service — the dedicated "what should happen next?" entry.

Phase 2 of the Autonomous Reasoning evolution. A single, reusable service that
answers "what should happen next?" for any caller (the Infinity loop today;
freelance/agent callers later) without being tied to the loop. It composes the
Phase 1 engine (`evaluate_state` + `decide`) with feedback analysis and strategy
selection through one common, input-driven interface.

Context gathering (DB/syscall reads) stays with callers/orchestrators; this
service is pure over its inputs so it is trivially testable and reusable.
"""

from __future__ import annotations

from typing import Any

from apps.analytics.services.reasoning.decision_engine import decide
from apps.analytics.services.reasoning.feedback_analyzer import summarize_feedback
from apps.analytics.services.reasoning.state_evaluator import evaluate_state
from apps.analytics.services.reasoning.strategy_selector import apply_strategy_accuracy
from apps.analytics.services.reasoning.types import ReasoningResult


def reason(
    score_snapshot: dict[str, Any] | None,
    *,
    feedback_context: dict[str, Any] | None = None,
    feedback_rows: list[Any] | None = None,
    memory_signals: list[dict[str, Any]] | None = None,
    system_state: dict[str, Any] | None = None,
    goals: list[dict[str, Any]] | None = None,
    social_signals: list[dict[str, Any]] | None = None,
    kpi_low: dict[str, Any] | None = None,
    strategy_accuracy: dict[str, float] | None = None,
) -> ReasoningResult:
    """Decide the next action from normalized reasoning inputs.

    - ``feedback_context`` may be passed directly, or ``feedback_rows`` to have the
      feedback analyzer summarize them.
    - ``strategy_accuracy`` (decision_type -> historical accuracy) opts into the
      strategy-selection pass; when provided, the chosen decision is adjusted by
      the accuracy recorded for it (penalize/boost/neutral). Pass ``{}`` to apply
      the pass with no history (annotates "unknown"); pass ``None`` to skip it.
    """
    if feedback_context is None and feedback_rows is not None:
        feedback_context = summarize_feedback(feedback_rows)

    snapshot = evaluate_state(
        score_snapshot,
        feedback_context=feedback_context,
        memory_signals=memory_signals,
        system_state=system_state,
        goals=goals,
        social_signals=social_signals,
        kpi_low=kpi_low,
    )
    result = decide(snapshot)

    if strategy_accuracy is not None:
        accuracy = strategy_accuracy.get(result.decision_type) if isinstance(strategy_accuracy, dict) else None
        decision_type, payload = apply_strategy_accuracy(result.decision_type, result.payload, accuracy)
        result = ReasoningResult(decision_type=decision_type, payload=payload)

    return result
