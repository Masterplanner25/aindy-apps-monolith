"""reasoning.evaluate agent tool (ARM/Reasoning Phase 3 follow-up).

Verifies the tool is registered, its function returns the reasoning
recommendation, and — crucially — its capability wiring resolves so plans using
it auto-approve rather than failing capability preflight.
"""

from __future__ import annotations

import pytest

from apps.analytics.agents.tools import reasoning_evaluate
from apps.analytics.services import reasoning as reasoning_pkg

pytestmark = pytest.mark.app_profile


def test_reasoning_evaluate_tool_registered():
    from AINDY.agents.tool_registry import TOOL_REGISTRY

    assert "reasoning.evaluate" in TOOL_REGISTRY
    entry = TOOL_REGISTRY["reasoning.evaluate"]
    assert entry["risk"] == "low"
    assert entry["egress_scope"] == "internal"
    assert callable(entry["fn"])


def test_reasoning_evaluate_returns_recommendation(monkeypatch):
    monkeypatch.setattr(
        reasoning_pkg,
        "recommend_next_action",
        lambda user_id, db: {
            "decision_type": "review_plan",
            "reason": "focus_below_threshold",
            "execution_intent": {"intent_type": "review_plan", "dispatch": "manual"},
        },
    )
    out = reasoning_evaluate({}, "user-1", object())
    assert out["available"] is True
    assert out["decision_type"] == "review_plan"
    assert out["execution_intent"]["dispatch"] == "manual"


def test_reasoning_evaluate_handles_missing_snapshot(monkeypatch):
    monkeypatch.setattr(reasoning_pkg, "recommend_next_action", lambda user_id, db: None)
    out = reasoning_evaluate({}, "user-1", object())
    assert out["available"] is False
    assert out["reason"] == "no_score_snapshot"


def test_reasoning_evaluate_capability_resolves_for_plan():
    # The decisive check: a plan using reasoning.evaluate must resolve a non-empty
    # capability set (base agent cap + the tool's capability), so the run
    # auto-approves instead of falling back to manual approval.
    from AINDY.agents.capability_service import get_plan_required_capabilities

    caps = get_plan_required_capabilities(
        {"steps": [{"tool": "reasoning.evaluate"}]}, "default"
    )
    assert "read_reasoning" in caps
    assert "execute_flow" in caps
