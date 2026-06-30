"""Support-state -> decision pipeline (Infinity Support System — Step 6).

Proves the assembled support snapshot actually changes Infinity decisions: the
memory signals gathered into `SupportState` (Step 1) and the feedback summarized by
the feedback analyzer (Step 5) flow through the same `loop_context` the loop builds
and flip the reasoning decision. This ties Step 1 + Step 5 + the decision engine
into one regression guard over the support -> decision seam.

The app-testable seam is `gather_support_state -> loop_context -> reason()`; the
full DB-backed `run_loop` persistence path (real execution outcome -> re-score ->
persisted adjustment) is exercised in the Postgres integration tier.
"""

from __future__ import annotations

import pytest

import apps.analytics.services.integration.dependency_adapter as adapter
from apps.analytics.services.orchestration import support_state as ss
from apps.analytics.services.reasoning import reason, summarize_feedback

pytestmark = pytest.mark.app_profile

_STABLE = {
    "master_score": 60.0,
    "execution_speed": 60.0,
    "decision_efficiency": 60.0,
    "focus_quality": 60.0,
    "ai_productivity_boost": 60.0,
}


def _snapshot(monkeypatch, *, memory_signals):
    """Build a SupportState whose only non-trivial input is memory_signals."""
    monkeypatch.setattr(adapter, "fetch_recent_memory", lambda *a, **k: [])
    monkeypatch.setattr(adapter, "fetch_user_metrics", lambda *a, **k: {})
    monkeypatch.setattr(adapter, "fetch_memory_signals", lambda **k: memory_signals)
    monkeypatch.setattr(adapter, "fetch_system_state", lambda db: {})
    monkeypatch.setattr(adapter, "fetch_task_graph_context", lambda db, uid: {})
    monkeypatch.setattr(adapter, "fetch_social_performance_signals", lambda **k: [])
    monkeypatch.setattr(ss, "get_job", lambda name: None)
    return ss.gather_support_state(object(), "u1", "manual")


def _decide_from_snapshot(support, *, feedback_context=None):
    # Mirror how run_loop feeds the snapshot's loop_context into the engine.
    lc = support.loop_context
    return reason(
        _STABLE,
        feedback_context=feedback_context,
        memory_signals=lc["memory_signals"],
        system_state=lc["system_state"],
        goals=lc["goals"],
        social_signals=lc["social_signals"],
    )


def test_memory_failure_signal_from_snapshot_flips_decision(monkeypatch):
    support = _snapshot(monkeypatch, memory_signals=[{"type": "failure", "weighted_score": 1.0}])
    result = _decide_from_snapshot(support)
    assert result.decision_type == "review_plan"
    assert result.payload["memory_adjustment"]["reason"] == "high_impact_failures_detected"


def test_clean_snapshot_continues(monkeypatch):
    support = _snapshot(monkeypatch, memory_signals=[])
    result = _decide_from_snapshot(support)
    # stable KPIs + no adverse signals -> stay the course
    assert result.decision_type == "continue_highest_priority_task"
    assert result.reason == "kpis_stable"


def test_success_signal_from_snapshot_does_not_flip(monkeypatch):
    support = _snapshot(monkeypatch, memory_signals=[{"type": "success", "weighted_score": 1.0}])
    result = _decide_from_snapshot(support)
    assert result.decision_type == "continue_highest_priority_task"


def test_negative_feedback_from_summary_flips_decision(monkeypatch):
    # Step 5 feedback analyzer -> feedback_context -> decision
    support = _snapshot(monkeypatch, memory_signals=[])
    feedback_context = summarize_feedback(
        [{"feedback_value": -1}, {"feedback_value": -1}, {"feedback_value": 1}]
    )
    result = _decide_from_snapshot(support, feedback_context=feedback_context)
    assert result.decision_type == "review_plan"
    assert result.reason == "recent_negative_feedback"


def test_snapshot_signals_are_what_the_engine_consumes(monkeypatch):
    # the seam: loop_context carries exactly the memory signals reason() reads
    signals = [{"type": "failure", "weighted_score": 1.0}]
    support = _snapshot(monkeypatch, memory_signals=signals)
    assert support.loop_context["memory_signals"] == signals
    result = _decide_from_snapshot(support)
    assert result.payload["memory_signals"] == signals
