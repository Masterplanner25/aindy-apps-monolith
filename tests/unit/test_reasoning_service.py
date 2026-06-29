"""Dedicated reasoning service + strategy/feedback components (ARM/Reasoning Phase 2).

Covers the strategy selector, the feedback analyzer, and the `reason()` service
that composes state evaluation, the decision engine, feedback analysis, and
strategy selection into one reusable "what should happen next?" entry point.
"""

from __future__ import annotations

import pytest

from apps.analytics.services.reasoning import (
    apply_strategy_accuracy,
    decide,
    evaluate_state,
    reason,
    summarize_feedback,
)

pytestmark = pytest.mark.app_profile

_STABLE = {
    "master_score": 60.0,
    "execution_speed": 60.0,
    "decision_efficiency": 60.0,
    "focus_quality": 60.0,
    "ai_productivity_boost": 60.0,
}


# --------------------------------------------------------------------------- #
# strategy_selector
# --------------------------------------------------------------------------- #
def test_strategy_accuracy_unknown_when_no_history():
    decision, payload = apply_strategy_accuracy("continue_highest_priority_task", {"reason": "x"}, None)
    assert decision == "continue_highest_priority_task"
    assert payload["strategy_accuracy"] == {"status": "unknown"}


def test_strategy_accuracy_penalizes_low_accuracy():
    decision, payload = apply_strategy_accuracy(
        "continue_highest_priority_task",
        {"reason": "kpis_stable", "next_action": {"type": "continue_highest_priority_task"}},
        0.2,
    )
    assert decision == "review_plan"
    assert payload["strategy_accuracy"]["status"] == "penalized"
    assert payload["reason"] == "kpis_stable|low_prediction_accuracy"
    assert payload["next_action"]["type"] == "review_plan"


def test_strategy_accuracy_does_not_penalize_review_plan():
    decision, payload = apply_strategy_accuracy("review_plan", {"reason": "focus_below_threshold"}, 0.1)
    assert decision == "review_plan"
    # already a review -> not flipped/penalized, just annotated
    assert payload["strategy_accuracy"]["status"] == "neutral"


def test_strategy_accuracy_boosts_high_accuracy():
    decision, payload = apply_strategy_accuracy(
        "continue_highest_priority_task",
        {"next_action": {"type": "continue_highest_priority_task"}},
        0.9,
    )
    assert decision == "continue_highest_priority_task"
    assert payload["strategy_accuracy"]["status"] == "boosted"
    assert payload["next_action"]["strategy_boost"] == "high_prediction_accuracy"


def test_strategy_accuracy_neutral_in_mid_band():
    _, payload = apply_strategy_accuracy("continue_highest_priority_task", {"next_action": {}}, 0.6)
    assert payload["strategy_accuracy"]["status"] == "neutral"


# --------------------------------------------------------------------------- #
# feedback_analyzer
# --------------------------------------------------------------------------- #
def test_summarize_feedback_empty():
    assert summarize_feedback([]) == {
        "count": 0,
        "positive": 0,
        "negative": 0,
        "latest_feedback_text": None,
    }


def test_summarize_feedback_counts_polarity_and_latest_text():
    rows = [
        {"feedback_value": 1, "feedback_text": "great"},
        {"feedback_value": -1, "feedback_text": None},
        {"feedback_value": -1, "feedback_text": "needs work"},
    ]
    summary = summarize_feedback(rows)
    assert summary["count"] == 3
    assert summary["positive"] == 1
    assert summary["negative"] == 2
    assert summary["latest_feedback_text"] == "great"


def test_summarize_feedback_accepts_objects():
    class Row:
        def __init__(self, value, text=None):
            self.feedback_value = value
            self.feedback_text = text

    summary = summarize_feedback([Row(1), Row(-1, "bad")])
    assert summary["positive"] == 1 and summary["negative"] == 1
    assert summary["latest_feedback_text"] == "bad"


# --------------------------------------------------------------------------- #
# autonomous_reasoning_service.reason()
# --------------------------------------------------------------------------- #
def test_reason_stable_without_strategy_pass():
    result = reason(dict(_STABLE))
    assert result.decision_type == "continue_highest_priority_task"
    assert result.reason == "kpis_stable"
    # no strategy pass requested -> no strategy_accuracy annotation
    assert "strategy_accuracy" not in result.payload


def test_reason_applies_strategy_accuracy_when_provided():
    result = reason(dict(_STABLE), strategy_accuracy={"continue_highest_priority_task": 0.2})
    assert result.decision_type == "review_plan"
    assert result.payload["strategy_accuracy"]["status"] == "penalized"


def test_reason_empty_strategy_map_annotates_unknown():
    # mirrors the loop path: _get_strategy_accuracy_context returns {} with no history
    result = reason(dict(_STABLE), strategy_accuracy={})
    assert result.payload["strategy_accuracy"] == {"status": "unknown"}


def test_reason_summarizes_feedback_rows():
    result = reason(
        dict(_STABLE),
        feedback_rows=[{"feedback_value": -1}, {"feedback_value": -1}, {"feedback_value": 1}],
    )
    assert result.decision_type == "review_plan"
    assert result.reason == "recent_negative_feedback"


def test_reason_matches_engine_plus_strategy_selector():
    # The service must equal: decide(evaluate_state(...)), then strategy selection,
    # then the attached execution intent (Phase 4).
    from apps.analytics.services.reasoning import build_execution_intent

    snap = {**_STABLE, "focus_quality": 5.0}
    accuracy_map = {"review_plan": 0.9}

    base = decide(evaluate_state(snap))
    decision_type, payload = apply_strategy_accuracy(
        base.decision_type, base.payload, accuracy_map.get(base.decision_type)
    )
    payload = {**payload, "execution_intent": build_execution_intent(decision_type, payload)}

    result = reason(snap, strategy_accuracy=accuracy_map)
    assert result.to_tuple() == (decision_type, payload)
