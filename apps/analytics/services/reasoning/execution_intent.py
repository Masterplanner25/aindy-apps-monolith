"""Execution intent — translate a reasoning decision into how it should execute.

Phase 4 of the Autonomous Reasoning evolution. `execution_intent` is one of the
reasoning layer's normalized outputs: given a decision, it says *how* that
decision should be carried out (a normalized intent type + dispatch mode), so
downstream execution (flow engine, agents, or the loop) can route on a stable
contract rather than re-deriving it. Pure.
"""

from __future__ import annotations

from typing import Any

# Decision type -> a stable, execution-oriented intent name.
_INTENT_BY_DECISION: dict[str, str] = {
    "continue_highest_priority_task": "advance_work",
    "create_new_task": "create_work",
    "reprioritize_tasks": "reprioritize_work",
    "review_plan": "review_plan",
}


def build_execution_intent(decision_type: str | None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map a reasoning decision to a normalized execution intent.

    ``dispatch`` describes who carries it out:
      - ``"manual"`` for advisory reviews (``review_plan``) — no auto-execution,
      - ``"loop"`` for task-shaping decisions the Infinity loop already enacts.
    """
    payload = payload or {}
    next_action = payload.get("next_action") or {}
    intent_type = _INTENT_BY_DECISION.get(decision_type or "", "review_plan")
    dispatch = "manual" if decision_type == "review_plan" else "loop"
    return {
        "intent_type": intent_type,
        "decision_type": decision_type,
        "dispatch": dispatch,
        "next_action_type": next_action.get("type"),
        "suggested_goal": next_action.get("suggested_goal") or payload.get("suggested_goal"),
    }
