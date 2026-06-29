"""Reasoning engine — Infinity loop decision logic (ARM/Reasoning Phase 1).

These start as *characterization* tests pinning the behavior of the decision
logic as it lived inline in `infinity_loop._decide`, then double as the
regression suite after that logic is extracted into
`apps/analytics/services/reasoning/`. `infinity_loop._decide` remains a thin
wrapper over the extracted engine, so the same assertions validate both the
public loop entry point and the new reusable module.
"""

from __future__ import annotations

import pytest

from apps.analytics.services.orchestration.infinity_loop import _decide
from apps.analytics.services.reasoning import (
    ReasoningResult,
    StateSnapshot,
    decide,
    evaluate_state,
)

pytestmark = pytest.mark.app_profile

_STABLE = {
    "master_score": 60.0,
    "execution_speed": 60.0,
    "decision_efficiency": 60.0,
    "focus_quality": 60.0,
    "ai_productivity_boost": 60.0,
}


def test_stable_kpis_continue_highest_priority_task():
    decision, payload = _decide(dict(_STABLE))
    assert decision == "continue_highest_priority_task"
    assert payload["reason"] == "kpis_stable"
    assert payload["next_action"]["type"] == "continue_highest_priority_task"


def test_negative_feedback_triggers_review_plan():
    decision, payload = _decide(dict(_STABLE), feedback_context={"negative": 3, "positive": 0})
    assert decision == "review_plan"
    assert payload["reason"] == "recent_negative_feedback"
    assert payload["next_action"]["type"] == "review_plan"


def test_missing_score_snapshot_is_insufficient_data():
    decision, payload = _decide(None)
    assert decision == "review_plan"
    assert payload["reason"] == "insufficient_data"


def test_invalid_score_snapshot():
    decision, payload = _decide({"execution_speed": "not-a-number"})
    assert decision == "review_plan"
    assert payload["reason"] == "invalid_snapshot"


def test_low_execution_speed_reprioritizes():
    snap = {**_STABLE, "execution_speed": 10.0}
    decision, payload = _decide(snap)
    assert decision == "reprioritize_tasks"
    assert payload["reason"] == "execution_or_decision_below_threshold"


def test_low_focus_quality_reviews_plan():
    snap = {**_STABLE, "focus_quality": 10.0}
    decision, payload = _decide(snap)
    assert decision == "review_plan"
    assert payload["reason"] == "focus_below_threshold"


def test_low_ai_boost_reviews_plan():
    snap = {**_STABLE, "ai_productivity_boost": 10.0}
    decision, payload = _decide(snap)
    assert decision == "review_plan"
    assert payload["reason"] == "ai_productivity_below_threshold"


def test_custom_kpi_low_thresholds_are_respected():
    # With a lower threshold, an execution_speed of 30 is no longer "low".
    snap = {**_STABLE, "execution_speed": 30.0}
    decision, _ = _decide(snap, kpi_low={"execution_speed": 20.0, "decision_efficiency": 20.0})
    assert decision == "continue_highest_priority_task"


def test_memory_failure_weight_flips_to_review_plan():
    decision, payload = _decide(
        dict(_STABLE),
        memory_signals=[{"type": "failure", "weighted_score": 1.0}],
    )
    assert decision == "review_plan"
    assert payload["memory_adjustment"]["reason"] == "high_impact_failures_detected"


def test_critical_system_state_forces_safe_mode_review():
    decision, payload = _decide(dict(_STABLE), system_state={"health_status": "critical"})
    assert decision == "review_plan"
    assert payload["next_action"]["safe_mode"] is True
    assert payload["system_adjustment"]["reason"] == "critical_system_health"


def test_low_social_performance_reviews_plan():
    decision, payload = _decide(
        dict(_STABLE),
        social_signals=[{"type": "failure", "engagement_score": 1.0}],
    )
    assert decision == "review_plan"
    assert payload["social_adjustment"]["reason"] == "low_social_performance"


def test_goal_summary_is_attached():
    decision, payload = _decide(
        dict(_STABLE),
        goals=[{"id": "g1", "name": "Ship v1", "ranked_priority": 0.8, "progress": 0.2}],
    )
    # Goal weighting always attaches a goal_summary; whether it flips the
    # decision depends on the registered alignment job, so only the summary is
    # pinned here.
    assert payload["goal_summary"]["goal_count"] == 1
    assert decision in {"continue_highest_priority_task", "review_plan"}


def test_stable_decision_carries_weighting_annotations():
    _, payload = _decide(dict(_STABLE))
    # every decision passes through the weighting refiners
    assert "memory_summary" in payload
    assert "system_adjustment" in payload
    assert "goal_summary" in payload
    assert "social_signals" in payload


# --------------------------------------------------------------------------- #
# New normalized reasoning API (state_evaluator + decision_engine)
# --------------------------------------------------------------------------- #
def test_evaluate_state_normalizes_empty_inputs():
    snapshot = evaluate_state(None)
    assert isinstance(snapshot, StateSnapshot)
    assert snapshot.has_score is False
    assert snapshot.valid_score is False
    assert snapshot.feedback_context == {}
    assert snapshot.memory_signals == [] and snapshot.goals == []
    assert snapshot.kpi_health == {}


def test_evaluate_state_flags_kpi_health():
    snapshot = evaluate_state({**_STABLE, "execution_speed": 10.0})
    assert snapshot.has_score is True
    assert snapshot.valid_score is True
    assert snapshot.kpi_health["execution_speed"]["below"] is True
    assert snapshot.kpi_health["focus_quality"]["below"] is False


def test_evaluate_state_marks_invalid_score():
    snapshot = evaluate_state({"execution_speed": "nope"})
    assert snapshot.has_score is True
    assert snapshot.valid_score is False


def test_decide_returns_normalized_reasoning_result():
    result = decide(evaluate_state(dict(_STABLE)))
    assert isinstance(result, ReasoningResult)
    assert result.decision_type == "continue_highest_priority_task"
    assert result.reason == "kpis_stable"
    assert result.next_action["type"] == "continue_highest_priority_task"
    # to_tuple() matches the legacy loop contract
    assert result.to_tuple() == (result.decision_type, result.payload)


def test_engine_matches_legacy_wrapper():
    # the wrapper and the engine must agree
    snap = {**_STABLE, "focus_quality": 5.0}
    wrapper_decision, wrapper_payload = _decide(snap)
    engine = decide(evaluate_state(snap))
    assert (engine.decision_type, engine.payload) == (wrapper_decision, wrapper_payload)
