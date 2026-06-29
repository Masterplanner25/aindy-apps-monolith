"""Reasoning observability events (ARM/Reasoning Phase 5).

Covers the pure record builder, the best-effort emitter (with an injected queue),
and that the reasoning event types are registered through the runtime's event
registration surface at bootstrap (no runtime edits).
"""

from __future__ import annotations

import pytest

from apps.analytics.services.reasoning import (
    REASONING_EVENT_TYPES,
    build_reasoning_records,
    emit_reasoning_records,
)
from apps.analytics.services.reasoning.reasoning_events import (
    REASONING_ACTION_SELECTED,
    REASONING_FEEDBACK_APPLIED,
    REASONING_STATE_EVALUATED,
    REASONING_STRATEGY_SELECTED,
)

pytestmark = pytest.mark.app_profile

_SCORE = {
    "master_score": 60.0,
    "execution_speed": 60.0,
    "decision_efficiency": 60.0,
    "focus_quality": 60.0,
    "ai_productivity_boost": 60.0,
}


def _types(records):
    return [r["event_type"] for r in records]


def test_minimal_decision_emits_state_and_action_only():
    records = build_reasoning_records(
        decision_type="continue_highest_priority_task",
        payload={"reason": "kpis_stable", "next_action": {"type": "continue_highest_priority_task", "title": "Go"}},
        score_snapshot=_SCORE,
    )
    assert _types(records) == [REASONING_STATE_EVALUATED, REASONING_ACTION_SELECTED]
    action = records[-1]["payload"]
    assert action["decision_type"] == "continue_highest_priority_task"
    assert action["reason"] == "kpis_stable"
    assert action["next_action_type"] == "continue_highest_priority_task"


def test_feedback_and_strategy_records_appear_when_present():
    records = build_reasoning_records(
        decision_type="review_plan",
        payload={
            "reason": "kpis_stable|low_prediction_accuracy",
            "next_action": {"type": "review_plan", "title": "Review"},
            "feedback_context": {"count": 3, "positive": 1, "negative": 2},
            "strategy_accuracy": {"status": "penalized", "accuracy": 0.2},
        },
        score_snapshot=_SCORE,
    )
    assert _types(records) == [
        REASONING_STATE_EVALUATED,
        REASONING_FEEDBACK_APPLIED,
        REASONING_STRATEGY_SELECTED,
        REASONING_ACTION_SELECTED,
    ]
    feedback = records[1]["payload"]
    assert feedback["negative"] == 2
    strategy = records[2]["payload"]
    assert strategy["status"] == "penalized" and strategy["accuracy"] == 0.2


def test_state_record_summarizes_loop_context():
    records = build_reasoning_records(
        decision_type="continue_highest_priority_task",
        payload={"next_action": {"type": "continue_highest_priority_task"}},
        score_snapshot=_SCORE,
        loop_context={
            "memory_signals": [{"type": "failure"}],
            "goals": [{"id": "g1"}, {"id": "g2"}],
            "social_signals": [],
            "system_state": {"health_status": "healthy"},
        },
    )
    state = records[0]["payload"]
    assert state["memory_signal_count"] == 1
    assert state["goal_count"] == 2
    assert state["system_health"] == "healthy"
    assert state["score"]["master_score"] == 60.0


def test_emit_reasoning_records_uses_injected_queue():
    calls = []

    def fake_queue(**kwargs):
        calls.append(kwargs)

    records = build_reasoning_records(
        decision_type="continue_highest_priority_task",
        payload={"next_action": {"type": "continue_highest_priority_task"}},
        score_snapshot=_SCORE,
    )
    emitted = emit_reasoning_records(records, db=object(), user_id="u1", trace_id="t1", queue=fake_queue)

    assert emitted == len(records)
    assert {c["event_type"] for c in calls} == set(_types(records))
    assert all(c["source"] == "reasoning" and c["required"] is False for c in calls)
    assert all(c["trace_id"] == "t1" and c["user_id"] == "u1" for c in calls)


def test_emit_reasoning_records_is_defensive():
    def boom(**kwargs):
        raise RuntimeError("event store down")

    records = build_reasoning_records(decision_type="x", payload={"next_action": {}}, score_snapshot=_SCORE)
    # never raises; reports zero successful emissions
    assert emit_reasoning_records(records, db=None, user_id="u", queue=boom) == 0


def test_emit_empty_records_is_noop():
    assert emit_reasoning_records([], db=None, user_id="u", queue=lambda **k: None) == 0


def test_reasoning_event_types_registered_at_bootstrap():
    from AINDY.platform_layer.registry import get_event_types

    registered = get_event_types()
    missing = [t for t in REASONING_EVENT_TYPES if t not in registered]
    assert not missing, f"reasoning event types not registered via register_event_type: {missing}"
