"""Reasoning execution intent + flow integration (ARM/Reasoning Phase 4).

Covers the normalized execution-intent output, its propagation through
`reason()` / `recommend_next_action`, the `reasoning.execution_intent_selected`
observability event, the reasoning flow node, and the registered reasoning flow
strategy (the runtime intent-execution integration point).
"""

from __future__ import annotations

import pytest

import apps.analytics.services.scoring.infinity_service as infinity_service
from apps.analytics.services import reasoning as reasoning_pkg
from apps.analytics.services.reasoning import (
    build_execution_intent,
    build_reasoning_records,
    reason,
    recommend_next_action,
    select_reasoning_flow,
)
from apps.analytics.services.reasoning.reasoning_events import (
    REASONING_EVENT_TYPES,
    REASONING_EXECUTION_INTENT_SELECTED,
)

pytestmark = pytest.mark.app_profile

_STABLE = {
    "master_score": 60.0,
    "execution_speed": 60.0,
    "decision_efficiency": 60.0,
    "focus_quality": 60.0,
    "ai_productivity_boost": 60.0,
}


def test_build_execution_intent_maps_decisions():
    advance = build_execution_intent("continue_highest_priority_task", {"next_action": {"type": "continue_highest_priority_task"}})
    assert advance["intent_type"] == "advance_work"
    assert advance["dispatch"] == "loop"

    review = build_execution_intent("review_plan", {"next_action": {"type": "review_plan"}})
    assert review["intent_type"] == "review_plan"
    assert review["dispatch"] == "manual"

    assert build_execution_intent("reprioritize_tasks", {})["intent_type"] == "reprioritize_work"
    assert build_execution_intent("create_new_task", {})["intent_type"] == "create_work"


def test_reason_attaches_execution_intent():
    result = reason(dict(_STABLE))
    intent = result.payload["execution_intent"]
    assert intent["decision_type"] == "continue_highest_priority_task"
    assert intent["intent_type"] == "advance_work"
    assert intent["dispatch"] == "loop"


def test_reason_execution_intent_reflects_final_decision():
    # low focus -> review_plan -> manual intent
    result = reason({**_STABLE, "focus_quality": 5.0})
    assert result.decision_type == "review_plan"
    assert result.payload["execution_intent"]["dispatch"] == "manual"


def test_recommend_next_action_includes_execution_intent(monkeypatch):
    monkeypatch.setattr(infinity_service, "get_user_kpi_snapshot", lambda **kw: dict(_STABLE))
    rec = recommend_next_action("user-1", object())
    assert rec["execution_intent"]["intent_type"] == "advance_work"


def test_execution_intent_event_in_event_types():
    assert REASONING_EXECUTION_INTENT_SELECTED in REASONING_EVENT_TYPES


def test_build_reasoning_records_emits_execution_intent_when_present():
    records = build_reasoning_records(
        decision_type="review_plan",
        payload={
            "reason": "focus_below_threshold",
            "next_action": {"type": "review_plan", "title": "Review"},
            "execution_intent": {"intent_type": "review_plan", "dispatch": "manual", "decision_type": "review_plan"},
        },
        score_snapshot=_STABLE,
    )
    intent_records = [r for r in records if r["event_type"] == REASONING_EXECUTION_INTENT_SELECTED]
    assert len(intent_records) == 1
    assert intent_records[0]["payload"]["intent_type"] == "review_plan"


def test_build_reasoning_records_omits_execution_intent_when_absent():
    records = build_reasoning_records(
        decision_type="continue_highest_priority_task",
        payload={"next_action": {"type": "continue_highest_priority_task"}},
        score_snapshot=_STABLE,
    )
    assert not any(r["event_type"] == REASONING_EXECUTION_INTENT_SELECTED for r in records)


def test_select_reasoning_flow_returns_executable_flow():
    flow = select_reasoning_flow({"flow_type": "reasoning", "intent_type": "reasoning", "db": None, "user_id": "u"})
    assert flow["start"] == "reasoning_apply_node"
    assert "reasoning_apply_node" in flow["end"]


def test_reasoning_apply_node_returns_recommendation(monkeypatch):
    from apps.analytics.flows.analytics_flows import reasoning_apply_node

    monkeypatch.setattr(
        reasoning_pkg,
        "recommend_next_action",
        lambda user_id, db: {"decision_type": "review_plan", "execution_intent": {"intent_type": "review_plan"}},
    )
    out = reasoning_apply_node({}, {"db": object(), "user_id": "user-1"})
    assert out["status"] == "SUCCESS"
    data = out["output_patch"]["reasoning_apply_result"]["data"]
    assert data["decision_type"] == "review_plan"


def test_reasoning_flow_strategy_registered_at_bootstrap():
    from AINDY.platform_layer.registry import get_flow_strategy

    # identity check: must be OUR strategy, not the "default" fallback
    assert get_flow_strategy("reasoning") is select_reasoning_flow
