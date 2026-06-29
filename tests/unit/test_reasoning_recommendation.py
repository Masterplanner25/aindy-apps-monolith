"""Reasoning recommendation bridge + agent planner integration (ARM/Reasoning Phase 3).

Covers the `recommend_next_action` bridge, its registration as the
`analytics.reasoning_recommendation` job, and the agent planner context block
that consumes it through the job registry (decoupled — no cross-app import).
"""

from __future__ import annotations

import pytest

import apps.analytics.services.scoring.infinity_service as infinity_service
from apps.analytics.services.reasoning import recommend_next_action

pytestmark = pytest.mark.app_profile

_STABLE = {
    "master_score": 60.0,
    "execution_speed": 60.0,
    "decision_efficiency": 60.0,
    "focus_quality": 60.0,
    "ai_productivity_boost": 60.0,
}


def test_recommend_next_action_stable(monkeypatch):
    monkeypatch.setattr(infinity_service, "get_user_kpi_snapshot", lambda **kw: dict(_STABLE))
    rec = recommend_next_action("user-1", object())
    assert rec["decision_type"] == "continue_highest_priority_task"
    assert rec["next_action_type"] == "continue_highest_priority_task"
    assert rec["reason"] == "kpis_stable"


def test_recommend_next_action_low_focus_reviews_plan(monkeypatch):
    monkeypatch.setattr(
        infinity_service, "get_user_kpi_snapshot", lambda **kw: {**_STABLE, "focus_quality": 10.0}
    )
    rec = recommend_next_action("user-1", object())
    assert rec["decision_type"] == "review_plan"
    assert rec["reason"] == "focus_below_threshold"


def test_recommend_next_action_none_when_no_snapshot(monkeypatch):
    monkeypatch.setattr(infinity_service, "get_user_kpi_snapshot", lambda **kw: None)
    assert recommend_next_action("user-1", object()) is None


def test_reasoning_recommendation_job_registered():
    from AINDY.platform_layer.registry import get_job

    assert get_job("analytics.reasoning_recommendation") is not None


# --------------------------------------------------------------------------- #
# Agent planner integration — consumes the recommendation via the job registry
# --------------------------------------------------------------------------- #
def test_agent_planner_reasoning_block_formats(monkeypatch):
    import AINDY.platform_layer.registry as registry
    from apps.agent.agents.runtime_extensions import _build_reasoning_context_block

    def fake_get_job(name):
        if name == "analytics.reasoning_recommendation":
            return lambda **kw: {
                "decision_type": "review_plan",
                "reason": "focus_below_threshold",
                "next_action_type": "review_plan",
                "next_action_title": "Review plan and refresh context",
                "suggested_goal": "Recall recent context first",
            }
        return None

    monkeypatch.setattr(registry, "get_job", fake_get_job)
    block = _build_reasoning_context_block("user-1", object())
    assert "Reasoning Recommendation" in block
    assert "review_plan" in block
    assert "Review plan and refresh context" in block
    assert "Recall recent context first" in block


def test_agent_planner_reasoning_block_empty_when_no_job(monkeypatch):
    import AINDY.platform_layer.registry as registry
    from apps.agent.agents.runtime_extensions import _build_reasoning_context_block

    monkeypatch.setattr(registry, "get_job", lambda name: None)
    assert _build_reasoning_context_block("user-1", object()) == ""


def test_agent_planner_reasoning_block_empty_when_no_recommendation(monkeypatch):
    import AINDY.platform_layer.registry as registry
    from apps.agent.agents.runtime_extensions import _build_reasoning_context_block

    monkeypatch.setattr(registry, "get_job", lambda name: (lambda **kw: None))
    assert _build_reasoning_context_block("user-1", object()) == ""
