"""MasterPlan reprojection returned from task completion (MASTERPLAN_SAAS Step 3).

Task completion already recomputes the active plan's ETA server-side, but the
(now cascade-aware) projection was discarded. It is now captured and surfaced in
the orchestration result, which flows through `task_orchestration` in the
`/tasks/complete` response so the MasterPlan surface can refresh with fresh
projection data.

The DB+syscall completion flow is integration-tier; here we cover the extracted
capture helper and the orchestration return contract on the app-profile harness.
"""

from __future__ import annotations

import uuid

import pytest

import apps.tasks.services.task_service as ts

pytestmark = pytest.mark.app_profile

_PROJECTION = {
    "masterplan_id": 7,
    "projected_completion_date": "2026-08-01",
    "days_ahead_behind": 24,
    "critical_depth": 6,
    "projection_basis": "cascade",
}


def test_recalc_captures_projection_for_active_plan(monkeypatch):
    monkeypatch.setattr(
        ts, "get_active_masterplan_via_syscall",
        lambda user_id, db: {"id": 7, "anchor_date": "2026-08-25T00:00:00Z"},
    )
    monkeypatch.setattr(ts, "get_eta_via_syscall", lambda plan_id, user_id, db: _PROJECTION)

    eta_recalculated, masterplan_id, projection = ts._recalculate_active_masterplan_eta(object(), "u1")
    assert eta_recalculated is True
    assert masterplan_id == 7
    assert projection == _PROJECTION
    assert projection["projection_basis"] == "cascade"


def test_recalc_noop_without_active_plan(monkeypatch):
    monkeypatch.setattr(ts, "get_active_masterplan_via_syscall", lambda user_id, db: None)
    monkeypatch.setattr(ts, "get_eta_via_syscall", lambda *a, **k: pytest.fail("should not be called"))

    assert ts._recalculate_active_masterplan_eta(object(), "u1") == (False, None, None)


def test_recalc_noop_when_plan_has_no_anchor(monkeypatch):
    monkeypatch.setattr(ts, "get_active_masterplan_via_syscall", lambda user_id, db: {"id": 7, "anchor_date": None})
    monkeypatch.setattr(ts, "get_eta_via_syscall", lambda *a, **k: pytest.fail("should not be called"))

    assert ts._recalculate_active_masterplan_eta(object(), "u1") == (False, None, None)


def test_recalc_is_defensive_on_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("masterplan syscall down")

    monkeypatch.setattr(ts, "get_active_masterplan_via_syscall", _boom)
    assert ts._recalculate_active_masterplan_eta(object(), "u1") == (False, None, None)


def test_orchestration_contract_includes_projection_keys(db_session):
    # No matching task -> early return; the contract must still carry the new keys.
    result = ts.orchestrate_task_completion(db_session, "does-not-exist", str(uuid.uuid4()))
    assert "masterplan_projection" in result
    assert "masterplan_id" in result
    assert result["masterplan_projection"] is None
    assert result["eta_recalculated"] is False
