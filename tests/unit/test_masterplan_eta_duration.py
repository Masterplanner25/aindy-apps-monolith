"""Continuous-time (per-task-duration) MasterPlan ETA (MASTERPLAN_SAAS Step: duration compression).

The cascade ETA (Step 1) counted tasks. When a plan's tasks carry effort
estimates (`Task.duration`, hours), the projection upgrades to continuous time:
task/day velocity is scaled by average task size into hours/day, and the
projection runs on remaining *effort* and the effort-weighted critical path
(`projection_basis="duration"`). It reduces to the count model when tasks are
uniform and falls back to it when no estimates exist.

Pure helpers (`_project_effort_days`, `_scope_plan_from_graph`) are tested
directly; the DB+syscall path (`calculate_eta`) runs on the SQLite harness with a
seeded plan and a monkeypatched graph dispatch.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.masterplan.models import MasterPlan
from apps.masterplan.services import eta_service as es

pytestmark = pytest.mark.app_profile


# --------------------------------------------------------------------------- #
# _project_effort_days — continuous-time math
# --------------------------------------------------------------------------- #
def test_effort_days_pure_throughput_when_no_chain():
    # 20h remaining at 10h/day, no critical chain -> 2 days
    assert es._project_effort_days(20.0, 10.0, 0.0) == pytest.approx(2.0)


def test_effort_days_chain_floor_binds_over_throughput():
    # throughput 22/10 = 2.2d, but a 20h chain at min(10,8)=8h/day = 2.5d wins
    assert es._project_effort_days(22.0, 10.0, 20.0) == pytest.approx(2.5)


def test_effort_days_chain_rate_capped_at_single_stream():
    # work_velocity 4h/day < 8 cap -> chain of 16h at 4h/day = 4 days
    assert es._project_effort_days(4.0, 4.0, 16.0) == pytest.approx(4.0)


def test_effort_days_zero_without_capacity_or_work():
    assert es._project_effort_days(20.0, 0.0, 10.0) == 0.0
    assert es._project_effort_days(0.0, 10.0, 10.0) == 0.0


# --------------------------------------------------------------------------- #
# _scope_plan_from_graph — effort metrics
# --------------------------------------------------------------------------- #
def _graph_with_durations():
    return {
        "nodes": {
            1: {"task_id": 1, "masterplan_id": 7, "status": "completed", "duration": 8},
            2: {"task_id": 2, "masterplan_id": 7, "status": "pending", "duration": 20},
            3: {"task_id": 3, "masterplan_id": 7, "status": "pending", "duration": 0},  # unestimated
            4: {"task_id": 4, "masterplan_id": 99, "status": "pending", "duration": 100},  # other plan
        },
        "critical_weight": {1: 1, 2: 1, 3: 1, 4: 1},
        "critical_duration": {1: 0, 2: 20, 3: 0, 4: 100},
        "ready": [2, 3],
        "blocked": [],
    }


def test_scope_derives_effort_metrics():
    scope = es._scope_plan_from_graph(_graph_with_durations(), 7)
    assert (scope["total"], scope["completed"], scope["remaining"]) == (3, 1, 2)
    # known durations 8 (completed) + 20 (task2) -> avg 14 (task3's 0 excluded)
    assert scope["avg_effort"] == pytest.approx(14.0)
    # remaining effort: task2 20h + task3 filled with avg 14h = 34h
    assert scope["remaining_effort"] == pytest.approx(34.0)
    # effort-weighted critical path over remaining tasks (task2's 20h chain)
    assert scope["critical_path_effort"] == pytest.approx(20.0)
    assert scope["has_duration_signal"] is True


def test_scope_no_duration_signal_when_estimates_absent():
    graph = {
        "nodes": {
            1: {"task_id": 1, "masterplan_id": 7, "status": "pending", "duration": 0},
            2: {"task_id": 2, "masterplan_id": 7, "status": "pending"},  # no duration key
        },
        "critical_weight": {1: 1, 2: 1},
        "ready": [1, 2],
        "blocked": [],
    }
    scope = es._scope_plan_from_graph(graph, 7)
    assert scope["has_duration_signal"] is False
    assert scope["remaining_effort"] == 0.0
    assert scope["avg_effort"] == 0.0


# --------------------------------------------------------------------------- #
# calculate_eta — duration basis integration
# --------------------------------------------------------------------------- #
def _seed_plan(db, user_id, *, plan_id, anchor_days=60):
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


def test_calculate_eta_uses_duration_basis_when_estimates_present(db_session, monkeypatch):
    user_id = str(uuid.uuid4())
    _seed_plan(db_session, user_id, plan_id=7, anchor_days=60)

    graph = {
        "nodes": {
            1: {"task_id": 1, "masterplan_id": 7, "status": "completed", "duration": 8},
            2: {"task_id": 2, "masterplan_id": 7, "status": "pending", "duration": 20},
            3: {"task_id": 3, "masterplan_id": 7, "status": "pending", "duration": 2},
        },
        "critical_weight": {1: 1, 2: 1, 3: 1},
        "critical_duration": {1: 0, 2: 20, 3: 2},
        "ready": [2, 3],
        "blocked": [],
    }

    def fake_dispatch(payload, *, db, user_id, capability):
        syscall = payload["_syscall"]
        if syscall == "sys.v1.task.count_completed_since":
            return {"count": 14}  # velocity 1.0 task/day
        if syscall == "sys.v1.tasks.get_graph_context":
            return graph
        if syscall == "sys.v1.task.count":
            return {"count": 999}  # must NOT be used
        return {}

    monkeypatch.setattr(es, "_dispatch_task_read", fake_dispatch)

    result = es.calculate_eta(db_session, 7, user_id)

    assert result["projection_basis"] == "duration"
    # avg task size = (8+20+2)/3 = 10h; work_velocity = 1.0/day * 10h = 10h/day
    assert result["work_velocity"] == pytest.approx(10.0)
    # remaining effort = 20 + 2 = 22h; chain = 20h
    assert result["remaining_effort"] == pytest.approx(22.0)
    assert result["critical_path_effort"] == pytest.approx(20.0)
    # cascade-count fields still reported
    assert (result["total_tasks"], result["completed_tasks"], result["remaining_tasks"]) == (3, 1, 2)
    assert result["days_ahead_behind"] is not None and result["days_ahead_behind"] > 0


def test_calculate_eta_stays_cascade_without_estimates(db_session, monkeypatch):
    user_id = str(uuid.uuid4())
    _seed_plan(db_session, user_id, plan_id=8)

    graph = {
        "nodes": {
            1: {"task_id": 1, "masterplan_id": 8, "status": "completed"},
            2: {"task_id": 2, "masterplan_id": 8, "status": "pending"},
        },
        "critical_weight": {1: 1, 2: 3},
        "critical_duration": {1: 0, 2: 0},
        "ready": [2],
        "blocked": [],
    }

    def fake_dispatch(payload, *, db, user_id, capability):
        syscall = payload["_syscall"]
        if syscall == "sys.v1.task.count_completed_since":
            return {"count": 14}
        if syscall == "sys.v1.tasks.get_graph_context":
            return graph
        return {}

    monkeypatch.setattr(es, "_dispatch_task_read", fake_dispatch)

    result = es.calculate_eta(db_session, 8, user_id)
    assert result["projection_basis"] == "cascade"
    assert result["remaining_effort"] == 0.0
    assert result["work_velocity"] == 0.0
