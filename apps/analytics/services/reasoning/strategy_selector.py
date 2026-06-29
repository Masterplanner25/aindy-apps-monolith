"""Strategy selector — adjust a decision by prior strategy accuracy.

Phase 2 of the Autonomous Reasoning evolution. This is the pure strategy
selection previously inlined in the Infinity loop's
``_apply_strategy_accuracy_weighting`` (the DB lookup of prior prediction
accuracy stays with the caller; only the decision adjustment lives here, so it is
reusable and testable). Behavior is preserved verbatim.
"""

from __future__ import annotations

from typing import Any


def apply_strategy_accuracy(
    decision_type: str,
    payload: dict[str, Any],
    accuracy: float | None,
) -> tuple[str, dict[str, Any]]:
    """Adjust ``(decision_type, payload)`` by the strategy's historical accuracy.

    - ``None`` accuracy -> annotate "unknown", no change.
    - ``< 0.45`` (and not already a review) -> penalize: flip to ``review_plan``.
    - ``> 0.75`` -> boost the chosen action.
    - otherwise -> neutral annotation.
    """
    if accuracy is None:
        return decision_type, {**payload, "strategy_accuracy": {"status": "unknown"}}

    adjusted_payload = {
        **payload,
        "strategy_accuracy": {
            "decision_type": decision_type,
            "accuracy": accuracy,
        },
    }
    if accuracy < 0.45 and decision_type != "review_plan":
        adjusted_payload["strategy_accuracy"]["status"] = "penalized"
        adjusted_payload["next_action"] = {
            "type": "review_plan",
            "title": "Review the plan because the current strategy has been inaccurate",
            "suggested_goal": "Correct course using the most recent outcome deviations",
        }
        adjusted_payload["reason"] = f"{payload.get('reason', 'strategy')}|low_prediction_accuracy"
        return "review_plan", adjusted_payload
    if accuracy > 0.75:
        adjusted_payload["strategy_accuracy"]["status"] = "boosted"
        next_action = dict(adjusted_payload.get("next_action") or {})
        next_action["strategy_boost"] = "high_prediction_accuracy"
        adjusted_payload["next_action"] = next_action
    else:
        adjusted_payload["strategy_accuracy"]["status"] = "neutral"
    return decision_type, adjusted_payload
