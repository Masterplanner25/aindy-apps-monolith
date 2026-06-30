"""Cascade-aware MasterPlan ETA (MASTERPLAN_SAAS Step 1).

ETA was flat task-velocity and counted tasks user-wide (a bug). It is now
plan-scoped and cascade-aware: remaining work is bounded by both throughput and
the longest remaining dependency chain (critical-path depth), with a graceful
fall back to the legacy velocity estimate when the task graph is unavailable.

Pure helpers (`_project_days`, `_scope_plan_from_graph`) are tested directly; the
DB+syscall path (`calculate_eta`) runs on the SQLite harness with a seeded plan
and a monkeypatched syscall dispatch.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.masterplan.models import MasterPlan
from apps.masterplan.services import eta_service as es

pytestmark = pytest.mark.app_profile


# --------------------------------------------------------------------------- #
# _project_days — cascade math
# --------------------------------------------------------------------------- #
def test_project_days_flat_when_no_chain():
    # 10 remaining at 2/day, depth 1 (independent) -> pure throughput
    assert es._project_days(10, 2.0, 1) == pytest.approx(5.0)


def test_project_days_deep_chain_extends_beyond_throughput():
    # depth 8 chain is sequential: floor 8/min(2,1)=8 > throughput 5
    assert es._project_days(10, 2.0, 8) == pytest.approx(8.0)


def test_project_days_zero_without_velocity_or_work():
    assert es._project_days(10, 0.0, 5) == 0.0
    assert es._project_days(0, 2.0, 5) == 0.0


# --------------------------------------------------------------------------- #
# _scope_plan_from_graph — plan scoping + cascade metrics
# --------------------------------------------------------------------------- #
def _graph():
    return {
        "nodes": {
            1: {"task_id": 1, "masterplan_id": 7, "status": "completed"},
            2: {"task_id": 2, "masterplan_id": 7, "status": "pending"},
            3: {"task_id": 3, "masterplan_id": 7, "status": "blocked"},
            4: {"task_id": 4, "masterplan_id": 99, "status": "pending"},  # other plan
        },
        "critical_weight": {1: 1, 2: 3, 3: 2, 4: 50},
        "ready": [2],
        "blocked": [3],
    }


def test_scope_filters_to_plan_and_derives_metrics():
    scope = es._scope_plan_from_graph(_graph(), 7)
    assert scope["total"] == 3            # tasks 1,2,3 — not the other plan's 4
    assert scope["completed"] == 1
    assert scope["remaining"] == 2
    assert scope["critical_depth"] == 3   # max weight over remaining (task 2)
    assert scope["ready_tasks"] == 1
    assert scope["blocked_tasks"] == 1


def test_scope_none_when_graph_empty():
    assert es._scope_plan_from_graph({"nodes": {}}, 7) is None
    assert es._scope_plan_from_graph({}, 7) is None


# --------------------------------------------------------------------------- #
# calculate_eta — integration over the seeded plan
# --------------------------------------------------------------------------- #
def _seed_plan(db, user_id, *, plan_id, anchor_days=30):
    now = datetime.now(timezone.utc)
    plan = MasterPlan(
        id=plan_id,
        start_date=now - timedelta(days=10),
        duration_years=1.0,
        target_date=now + timedelta(days=355),
        user_id=uuid.UUID(user_id),
        anchor_date=now + timedelta(days=anchor_days),
        status="active",
        is_active=True,
    )
    db.add(plan)
    db.commit()
    return plan


def test_calculate_eta_is_plan_scoped_and_cascade_aware(db_session, monkeypatch):
    user_id = str(uuid.uuid4())
    _seed_plan(db_session, user_id, plan_id=7, anchor_days=30)

    graph = {
        "nodes": {
            1: {"task_id": 1, "masterplan_id": 7, "status": "completed"},
            2: {"task_id": 2, "masterplan_id": 7, "status": "pending"},
            3: {"task_id": 3, "masterplan_id": 7, "status": "blocked"},
            9: {"task_id": 9, "masterplan_id": 99, "status": "pending"},  # ignored
        },
        "critical_weight": {1: 1, 2: 6, 3: 5, 9: 50},
        "ready": [2],
        "blocked": [3],
    }

    def fake_dispatch(payload, *, db, user_id, capability):
        syscall = payload["_syscall"]
        if syscall == "sys.v1.task.count_completed_since":
            return {"count": 14}  # velocity 1.0/day
        if syscall == "sys.v1.tasks.get_graph_context":
            return graph
        if syscall == "sys.v1.task.count":
            return {"count": 999}  # legacy fallback — must NOT be used here
        return {}

    monkeypatch.setattr(es, "_dispatch_task_read", fake_dispatch)

    result = es.calculate_eta(db_session, 7, user_id)

    assert result["projection_basis"] == "cascade"
    assert (result["total_tasks"], result["completed_tasks"], result["remaining_tasks"]) == (3, 1, 2)
    assert result["critical_depth"] == 6  # longest remaining chain
    assert result["ready_tasks"] == 1 and result["blocked_tasks"] == 1
    assert result["velocity"] == pytest.approx(1.0)
    # remaining 2 / vel 1 = 2 days throughput; chain 6/min(1,1)=6 -> 6 days wins
    # projected ~today+6, anchor today+30 -> ahead
    assert result["days_ahead_behind"] is not None and result["days_ahead_behind"] > 0
    assert result["eta_confidence"] == "high"

    plan = db_session.query(MasterPlan).filter(MasterPlan.id == 7).one()
    assert plan.current_velocity == pytest.approx(1.0)
    assert plan.eta_confidence == "high"
    assert plan.days_ahead_behind == result["days_ahead_behind"]


def test_calculate_eta_falls_back_to_velocity_when_graph_unavailable(db_session, monkeypatch):
    user_id = str(uuid.uuid4())
    _seed_plan(db_session, user_id, plan_id=8)

    def fake_dispatch(payload, *, db, user_id, capability):
        syscall = payload["_syscall"]
        if syscall == "sys.v1.task.count_completed_since":
            return {"count": 14}
        if syscall == "sys.v1.tasks.get_graph_context":
            return {}  # unavailable -> fallback
        if syscall == "sys.v1.task.count":
            return {"count": 4 if payload.get("status") == "completed" else 10}
        return {}

    monkeypatch.setattr(es, "_dispatch_task_read", fake_dispatch)

    result = es.calculate_eta(db_session, 8, user_id)

    assert result["projection_basis"] == "velocity"
    assert (result["total_tasks"], result["completed_tasks"], result["remaining_tasks"]) == (10, 4, 6)
    assert result["critical_depth"] == 0


def test_calculate_eta_missing_plan_raises(db_session, monkeypatch):
    monkeypatch.setattr(es, "_dispatch_task_read", lambda *a, **k: {"count": 0})
    with pytest.raises(ValueError):
        es.calculate_eta(db_session, 999999, str(uuid.uuid4()))
