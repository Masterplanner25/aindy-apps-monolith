"""Work Complexity Units (WCU) — MasterPlan physics.

``MasterPlan.total_wcu`` is the accumulated work-complexity of a plan's COMPLETED tasks
(``effort_hours × complexity × difficulty``) — the workload currency the phase gate
(``projection_service.evaluate_phase``) checks against ``wcu_target``. It was declared in the
schema but never computed, leaving both the value and the gate inert. These tests cover the
pure sum (``compute_total_wcu``) and the DB + phase-re-eval path (``calculate_wcu``), mirroring
the ETA harness (seeded plan + monkeypatched graph dispatch).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.masterplan.models import MasterPlan
from apps.masterplan.services import eta_service as es
from apps.masterplan.services import wcu_service as ws

pytestmark = pytest.mark.app_profile


# --------------------------------------------------------------------------- #
# compute_total_wcu / _task_wcu — pure functions
# --------------------------------------------------------------------------- #
def _graph():
    return {
        "nodes": {
            # completed, plan 7: 8h × complexity 2 × difficulty 1 = 16
            1: {"task_id": 1, "masterplan_id": 7, "status": "completed", "duration": 8,
                "task_complexity": 2, "task_difficulty": 1},
            # completed, plan 7, unestimated → default 1h × 3 × 2 = 6
            2: {"task_id": 2, "masterplan_id": 7, "status": "completed", "duration": 0,
                "task_complexity": 3, "task_difficulty": 2},
            # pending → ignored (WCU is work DONE)
            3: {"task_id": 3, "masterplan_id": 7, "status": "pending", "duration": 20,
                "task_complexity": 5, "task_difficulty": 5},
            # other plan → ignored
            4: {"task_id": 4, "masterplan_id": 99, "status": "completed", "duration": 40,
                "task_complexity": 4, "task_difficulty": 4},
        }
    }


def test_compute_total_wcu_sums_completed_plan_tasks():
    total, completed = ws.compute_total_wcu(_graph(), 7)
    assert total == pytest.approx(22.0)   # 16 + 6
    assert completed == 2


def test_compute_total_wcu_scopes_to_plan():
    total, completed = ws.compute_total_wcu(_graph(), 99)
    assert total == pytest.approx(640.0)  # 40 × 4 × 4
    assert completed == 1


def test_compute_total_wcu_empty_or_bad_plan_id():
    assert ws.compute_total_wcu({"nodes": {}}, 7) == (0.0, 0)
    assert ws.compute_total_wcu({}, None) == (0.0, 0)


def test_task_wcu_defaults_and_clamps():
    # no fields → default 1h × 1 × 1
    assert ws._task_wcu({"status": "completed"}) == pytest.approx(1.0)
    # complexity/difficulty clamp to >= 1 (0 must not zero out the work)
    assert ws._task_wcu({"duration": 4, "task_complexity": 0, "task_difficulty": 0}) == pytest.approx(4.0)
    # full multiply
    assert ws._task_wcu({"duration": 5, "task_complexity": 3, "task_difficulty": 2}) == pytest.approx(30.0)


# --------------------------------------------------------------------------- #
# calculate_wcu — DB integration + phase re-eval
# --------------------------------------------------------------------------- #
def _seed_plan(db, user_id, *, plan_id, **kw):
    now = datetime.now(timezone.utc)
    plan = MasterPlan(
        id=plan_id,
        start_date=now - timedelta(days=10),
        duration_years=1.0,
        target_date=now + timedelta(days=355),
        user_id=uuid.UUID(user_id),
        status="active",
        is_active=True,
        **kw,
    )
    db.add(plan)
    db.commit()
    return plan


def _patch_graph(monkeypatch, graph):
    def fake_dispatch(payload, *, db, user_id, capability):
        if payload["_syscall"] == "sys.v1.tasks.get_graph_context":
            return graph
        return {}
    monkeypatch.setattr(es, "_dispatch_task_read", fake_dispatch)


def test_calculate_wcu_persists_total_and_reevaluates_phase(db_session, monkeypatch):
    user_id = str(uuid.uuid4())
    _seed_plan(db_session, user_id, plan_id=7, wcu_target=10.0)
    _patch_graph(monkeypatch, _graph())

    result = ws.calculate_wcu(db_session, 7, user_id)
    assert result["total_wcu"] == pytest.approx(22.0)
    assert result["completed_tasks"] == 2   # not the pending or other-plan task

    plan = db_session.query(MasterPlan).filter(MasterPlan.id == 7).first()
    assert plan.total_wcu == pytest.approx(22.0)   # persisted
    # phase was actually evaluated (the gate was previously never called); with WCU met but
    # the other default thresholds (revenue 100k, books 3, platform, studio) unmet, it holds at 1.
    assert result["phase"] == 1
    assert result["phase_advanced"] is False


def test_calculate_wcu_phase_advances_when_all_thresholds_met(db_session, monkeypatch):
    """WCU is one gate among several — with every threshold satisfied (incl. the now-computed
    WCU), evaluate_phase advances 1 -> 2. Proves the previously-dead gate is live."""
    user_id = str(uuid.uuid4())
    _seed_plan(
        db_session, user_id, plan_id=8,
        wcu_target=10.0,
        revenue_target=0, gross_revenue=0,
        books_required=0, books_published=0,
        platform_required=False, studio_required=False,
        playbooks_required=0, active_playbooks=0,
    )
    # reuse the plan-7 graph but point its completed tasks at plan 8
    graph = {"nodes": {
        1: {"task_id": 1, "masterplan_id": 8, "status": "completed", "duration": 8,
            "task_complexity": 2, "task_difficulty": 1},
    }}
    _patch_graph(monkeypatch, graph)

    result = ws.calculate_wcu(db_session, 8, user_id)
    assert result["total_wcu"] == pytest.approx(16.0)   # 8 × 2 × 1 >= wcu_target 10
    assert result["phase"] == 2
    assert result["phase_advanced"] is True


def test_calculate_wcu_zero_when_no_completed_tasks(db_session, monkeypatch):
    user_id = str(uuid.uuid4())
    _seed_plan(db_session, user_id, plan_id=9)
    _patch_graph(monkeypatch, {"nodes": {
        1: {"task_id": 1, "masterplan_id": 9, "status": "pending", "duration": 20,
            "task_complexity": 5, "task_difficulty": 5},
    }})
    result = ws.calculate_wcu(db_session, 9, user_id)
    assert result["total_wcu"] == 0.0
    assert result["completed_tasks"] == 0
