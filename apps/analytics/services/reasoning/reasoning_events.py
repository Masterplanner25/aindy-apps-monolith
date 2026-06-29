"""Reasoning observability events (ARM/Reasoning Phase 5).

Makes reasoning decisions inspectable through the durable SystemEvent ledger /
RippleTrace — entirely via the runtime's registration + emission surface
(`register_event_type` + `queue_system_event`), with no runtime edits.

`build_reasoning_records` is pure (testable); `emit_reasoning_records` performs
best-effort emission and never raises into the decision path.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

REASONING_STATE_EVALUATED = "reasoning.state_evaluated"
REASONING_FEEDBACK_APPLIED = "reasoning.feedback_applied"
REASONING_STRATEGY_SELECTED = "reasoning.strategy_selected"
REASONING_ACTION_SELECTED = "reasoning.action_selected"

REASONING_EVENT_TYPES: tuple[str, ...] = (
    REASONING_STATE_EVALUATED,
    REASONING_FEEDBACK_APPLIED,
    REASONING_STRATEGY_SELECTED,
    REASONING_ACTION_SELECTED,
)


def build_reasoning_records(
    *,
    decision_type: str | None,
    payload: dict[str, Any] | None,
    score_snapshot: dict[str, Any] | None = None,
    loop_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the reasoning event records for one decision.

    Always emits ``state_evaluated`` and ``action_selected``; emits
    ``feedback_applied`` / ``strategy_selected`` only when those inputs were
    actually part of the decision (so the trace reflects state -> [feedback] ->
    [strategy] -> action).
    """
    payload = payload or {}
    score_snapshot = score_snapshot or {}
    loop_context = loop_context or {}
    records: list[dict[str, Any]] = []

    records.append(
        {
            "event_type": REASONING_STATE_EVALUATED,
            "payload": {
                "score": {
                    "master_score": score_snapshot.get("master_score"),
                    "execution_speed": score_snapshot.get("execution_speed"),
                    "decision_efficiency": score_snapshot.get("decision_efficiency"),
                    "focus_quality": score_snapshot.get("focus_quality"),
                    "ai_productivity_boost": score_snapshot.get("ai_productivity_boost"),
                },
                "memory_signal_count": len(loop_context.get("memory_signals") or []),
                "goal_count": len(loop_context.get("goals") or []),
                "social_signal_count": len(loop_context.get("social_signals") or []),
                "system_health": (loop_context.get("system_state") or {}).get("health_status"),
            },
        }
    )

    feedback_context = payload.get("feedback_context")
    if feedback_context:
        records.append(
            {
                "event_type": REASONING_FEEDBACK_APPLIED,
                "payload": {
                    "count": feedback_context.get("count"),
                    "positive": feedback_context.get("positive"),
                    "negative": feedback_context.get("negative"),
                },
            }
        )

    strategy_accuracy = payload.get("strategy_accuracy")
    if strategy_accuracy:
        records.append(
            {
                "event_type": REASONING_STRATEGY_SELECTED,
                "payload": {
                    "decision_type": decision_type,
                    "status": strategy_accuracy.get("status"),
                    "accuracy": strategy_accuracy.get("accuracy"),
                },
            }
        )

    next_action = payload.get("next_action") or {}
    records.append(
        {
            "event_type": REASONING_ACTION_SELECTED,
            "payload": {
                "decision_type": decision_type,
                "reason": payload.get("reason"),
                "next_action_type": next_action.get("type"),
                "next_action_title": next_action.get("title"),
            },
        }
    )
    return records


def emit_reasoning_records(
    records: list[dict[str, Any]],
    *,
    db,
    user_id,
    trace_id: str | None = None,
    queue: Callable[..., Any] | None = None,
) -> int:
    """Emit reasoning records as durable events. Best-effort, never raises.

    ``queue`` defaults to the runtime's ``queue_system_event``; it is injectable
    so emission is unit-testable without a live event store.
    """
    if not records:
        return 0
    if queue is None:
        from AINDY.core.execution_signal_helper import queue_system_event as queue

    emitted = 0
    for record in records:
        try:
            queue(
                db=db,
                event_type=record["event_type"],
                user_id=user_id,
                trace_id=trace_id,
                source="reasoning",
                payload=record.get("payload") or {},
                required=False,
            )
            emitted += 1
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[reasoning] event emit skipped (%s): %s", record.get("event_type"), exc)
    return emitted
