"""
Regression: task completion is idempotent (TASK-COMPLETE-IDEMPOTENCY-1).

A repeated ``complete_task`` on an already-completed task must be a no-op — it must
not re-fire the side-effect chain (TASK_COMPLETED event, downstream unlock,
ExecutionUnit update, the Infinity re-score + memory capture, time_spent re-accrual).
Re-firing double-counts the signal substrate the Infinity loop depends on.

Side effects are monkeypatched to counters so the test asserts they run exactly once
per logical completion — hermetic, no real syscalls.
"""
from __future__ import annotations

import uuid

import pytest

import apps.tasks.services.task_service as ts
from apps.tasks.models import Task

pytestmark = pytest.mark.app_profile


def _seed_task(db, user_id: str, *, name: str, status: str = "pending") -> Task:
    task = Task(name=name, status=status, user_id=uuid.UUID(user_id))
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_repeat_completion_does_not_refire_side_effects(db_session, monkeypatch):
    uid = str(uuid.uuid4())
    _seed_task(db_session, uid, name="t1")

    calls = {"unlock": 0, "event": 0, "calc": 0}
    monkeypatch.setattr(ts, "_unlock_downstream_tasks", lambda *a, **k: (calls.__setitem__("unlock", calls["unlock"] + 1) or []))
    monkeypatch.setattr(ts, "_emit_task_event", lambda *a, **k: calls.__setitem__("event", calls["event"] + 1))
    monkeypatch.setattr(ts, "save_calculation_via_syscall", lambda *a, **k: calls.__setitem__("calc", calls["calc"] + 1))

    first = ts.complete_task(db_session, "t1", user_id=uid)
    assert "Completed task" in first
    assert calls == {"unlock": 1, "event": 1, "calc": 1}

    second = ts.complete_task(db_session, "t1", user_id=uid)
    assert "already completed" in second.lower()
    assert calls == {"unlock": 1, "event": 1, "calc": 1}  # unchanged — no re-fire


def test_completed_task_completion_is_immediate_noop(db_session, monkeypatch):
    uid = str(uuid.uuid4())
    _seed_task(db_session, uid, name="t2", status="completed")

    monkeypatch.setattr(ts, "_unlock_downstream_tasks", lambda *a, **k: pytest.fail("downstream unlock re-fired"))
    monkeypatch.setattr(ts, "_emit_task_event", lambda *a, **k: pytest.fail("TASK_COMPLETED re-emitted"))
    monkeypatch.setattr(ts, "save_calculation_via_syscall", lambda *a, **k: pytest.fail("calculation re-saved"))

    result = ts.complete_task(db_session, "t2", user_id=uid)
    assert "already completed" in result.lower()


def test_repeat_completion_does_not_reaccrue_time_spent(db_session, monkeypatch):
    uid = str(uuid.uuid4())
    from datetime import datetime, timedelta

    task = _seed_task(db_session, uid, name="t3")
    # start_time set but not cleared on completion — the un-guarded path would
    # re-accrue elapsed time on every repeat call.
    task.start_time = datetime.now() - timedelta(seconds=100)
    db_session.commit()

    monkeypatch.setattr(ts, "_unlock_downstream_tasks", lambda *a, **k: [])
    monkeypatch.setattr(ts, "_emit_task_event", lambda *a, **k: None)
    monkeypatch.setattr(ts, "save_calculation_via_syscall", lambda *a, **k: None)

    ts.complete_task(db_session, "t3", user_id=uid)
    db_session.refresh(task)
    accrued_once = task.time_spent
    assert accrued_once >= 100

    ts.complete_task(db_session, "t3", user_id=uid)  # repeat — must be a no-op
    db_session.refresh(task)
    assert task.time_spent == accrued_once  # not re-accrued
