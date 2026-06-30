"""Centralized support-state snapshot (Infinity Support System — Step 1).

Verifies `gather_support_state` assembles the normalized snapshot the orchestrator
consumes, with the exact failure semantics it replaced: memory/metrics/signals
propagate; system_state/goals/task_graph/social_signals fall back to safe
defaults. The dependency-adapter reads + `goals.rank` job are monkeypatched.
"""

from __future__ import annotations

import pytest

import apps.analytics.services.integration.dependency_adapter as adapter
from apps.analytics.services.orchestration import support_state as ss

pytestmark = pytest.mark.app_profile


def _set_happy_fetchers(monkeypatch):
    monkeypatch.setattr(adapter, "fetch_recent_memory", lambda *a, **k: [{"id": "m1"}])
    monkeypatch.setattr(adapter, "fetch_user_metrics", lambda *a, **k: {"x": 1})
    monkeypatch.setattr(adapter, "fetch_memory_signals", lambda **k: [{"type": "failure"}])
    monkeypatch.setattr(adapter, "fetch_system_state", lambda db: {"health_status": "healthy"})
    monkeypatch.setattr(adapter, "fetch_task_graph_context", lambda db, uid: {"ready": [1], "blocked": []})
    monkeypatch.setattr(adapter, "fetch_social_performance_signals", lambda **k: [{"type": "success"}])
    monkeypatch.setattr(ss, "get_job", lambda name: (lambda db, uid, system_state=None: [{"id": "g1"}]))


def test_gather_support_state_assembles_snapshot(monkeypatch):
    _set_happy_fetchers(monkeypatch)
    state = ss.gather_support_state(object(), "u1", "manual")

    assert state.user_id == "u1"
    assert state.memory == [{"id": "m1"}]
    assert state.metrics == {"x": 1}
    assert state.memory_signals == [{"type": "failure"}]
    assert state.system_state == {"health_status": "healthy"}
    assert state.goals == [{"id": "g1"}]
    assert state.task_graph == {"ready": [1], "blocked": []}
    assert state.social_signals == [{"type": "success"}]


def test_loop_context_shape_matches_orchestrator_contract(monkeypatch):
    _set_happy_fetchers(monkeypatch)
    lc = ss.gather_support_state(object(), "u1", "manual").loop_context
    assert set(lc) == {
        "user_id", "memory", "metrics", "memory_signals",
        "system_state", "goals", "task_graph", "social_signals",
    }
    assert lc["user_id"] == "u1"
    assert lc["goals"] == [{"id": "g1"}]


def test_summary_counts(monkeypatch):
    _set_happy_fetchers(monkeypatch)
    summary = ss.gather_support_state(object(), "u1", "manual").summary()
    assert summary["memory_count"] == 1
    assert summary["memory_signal_count"] == 1
    assert summary["goal_count"] == 1
    assert summary["ready_task_count"] == 1
    assert summary["blocked_task_count"] == 0
    assert summary["social_signal_count"] == 1
    assert summary["health_status"] == "healthy"
    assert summary["has_metrics"] is True


def test_optional_inputs_fall_back_to_defaults(monkeypatch):
    monkeypatch.setattr(adapter, "fetch_recent_memory", lambda *a, **k: [])
    monkeypatch.setattr(adapter, "fetch_user_metrics", lambda *a, **k: None)
    monkeypatch.setattr(adapter, "fetch_memory_signals", lambda **k: [])

    def _boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(adapter, "fetch_system_state", _boom)
    monkeypatch.setattr(adapter, "fetch_task_graph_context", _boom)
    monkeypatch.setattr(adapter, "fetch_social_performance_signals", _boom)
    monkeypatch.setattr(ss, "get_job", lambda name: None)  # no goals job registered

    state = ss.gather_support_state(object(), "u1", "manual")
    assert state.system_state == {}
    assert state.goals == []
    assert state.task_graph == {}
    assert state.social_signals == []
    assert state.summary()["has_metrics"] is False


def test_goal_ranking_failure_defaults_to_empty(monkeypatch):
    _set_happy_fetchers(monkeypatch)

    def _boom_rank(db, uid, system_state=None):
        raise RuntimeError("rank failed")

    monkeypatch.setattr(ss, "get_job", lambda name: _boom_rank)
    assert ss.gather_support_state(object(), "u1", "manual").goals == []


def test_core_memory_failure_propagates(monkeypatch):
    # memory/metrics/signals are NOT swallowed (matches prior orchestrator behavior)
    def _boom(*a, **k):
        raise RuntimeError("memory store down")

    monkeypatch.setattr(adapter, "fetch_recent_memory", _boom)
    with pytest.raises(RuntimeError):
        ss.gather_support_state(object(), "u1", "manual")
