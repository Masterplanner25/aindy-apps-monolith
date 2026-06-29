"""Reasoning recommendation bridge (ARM/Reasoning Phase 3).

A thin DB-bound adapter that turns a user's current KPI snapshot into a compact
reasoning recommendation via the `reason()` service. Exposed as the
``analytics.reasoning_recommendation`` job so other domains (e.g. the agent
planner) can consume "what should happen next?" through the job registry — no
cross-app import, no runtime edit.

This is intentionally lightweight (KPI-only, no orchestrator-level context
gather): it informs planning without running the full Infinity loop.
"""

from __future__ import annotations

from typing import Any

from apps.analytics.services.reasoning.autonomous_reasoning_service import reason


def recommend_next_action(user_id: Any, db: Any) -> dict[str, Any] | None:
    """Return a compact reasoning recommendation for ``user_id``, or None.

    Shape: ``{decision_type, reason, next_action_type, next_action_title,
    suggested_goal}``.
    """
    from apps.analytics.services.scoring.infinity_service import get_user_kpi_snapshot

    snapshot = get_user_kpi_snapshot(user_id=user_id, db=db)
    if not snapshot:
        return None

    result = reason(snapshot)
    next_action = result.next_action or {}
    return {
        "decision_type": result.decision_type,
        "reason": result.reason,
        "next_action_type": next_action.get("type"),
        "next_action_title": next_action.get("title"),
        "suggested_goal": next_action.get("suggested_goal") or result.suggested_goal,
    }
