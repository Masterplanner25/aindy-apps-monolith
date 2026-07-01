"""Duration-weighted critical path + estimated-effort task creation.

Supports the continuous-time MasterPlan ETA (MASTERPLAN_SAAS duration
compression). `build_task_graph` now exposes per-node `duration` (hours) and a
`critical_duration` map — the effort-weighted longest remaining dependency chain,
with completed nodes contributing 0. Task creation accepts `estimated_hours`,
persisted to `Task.duration`.
"""

from __future__ import annotations

import uuid

import pytest

from apps.tasks.models import Task
from apps.tasks.services import task_service as ts

pytestmark = pytest.mark.app_profile


def _task(task_id, deps, duration, status="pending"):
    t = Task(
        name=f"t{task_id}",
        priority="medium",
        status=status,
        depends_on=[{"task_id": d} for d in deps],
        duration=duration,
    )
    t.id = task_id
    return t


def test_critical_duration_sums_effort_along_chain():
    # 1 -> 2 -> 3, durations 2h / 3h / 4h
    graph = ts.build_task_graph([
        _task(1, [], 2.0),
        _task(2, [1], 3.0),
        _task(3, [2], 4.0),
    ])
    cd = graph["critical_duration"]
    assert cd[3] == pytest.approx(4.0)   # leaf: its own effort
    assert cd[2] == pytest.approx(7.0)   # 3 + downstream 4
    assert cd[1] == pytest.approx(9.0)   # 2 + downstream 7
    # per-node duration is exposed
    assert graph["nodes"][2]["duration"] == pytest.approx(3.0)


def test_critical_duration_excludes_completed_effort():
    # 1 completed (its 5h is already done) -> 2 pending 3h
    graph = ts.build_task_graph([
        _task(1, [], 5.0, status="completed"),
        _task(2, [1], 3.0),
    ])
    cd = graph["critical_duration"]
    assert cd[2] == pytest.approx(3.0)
    assert cd[1] == pytest.approx(3.0)   # completed node adds 0, inherits downstream 3


def test_missing_or_zero_duration_is_zero_weight():
    t = Task(name="t1", priority="medium", status="pending", depends_on=[])
    t.id = 1
    t.duration = 0.0
    graph = ts.build_task_graph([t])
    assert graph["nodes"][1]["duration"] == 0.0
    assert graph["critical_duration"][1] == 0.0


def test_create_task_persists_estimated_hours_as_duration(db_session):
    user_id = str(uuid.uuid4())
    task = ts.create_task(
        db_session,
        name="Write spec",
        duration=3.5,
        user_id=user_id,
    )
    assert task.duration == pytest.approx(3.5)
    assert ts.build_task_graph([task])["nodes"][task.id]["duration"] == pytest.approx(3.5)


def test_create_task_defaults_duration_to_zero(db_session):
    user_id = str(uuid.uuid4())
    task = ts.create_task(db_session, name="No estimate", user_id=user_id)
    assert task.duration == 0.0
