"""Three-axis Infinity score — observability snapshot (Phase A).

Covers the Volume / Worth / Trajectory computations, the declared-worth CRUD, and the
core Phase-A invariant: computing the snapshot never touches the canonical master_score.
Runs on the SQLite app-profile harness.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from apps.analytics.services.scoring import three_axis_service as tas
from apps.analytics.services.scoring.value_declaration_service import (
    declared_worth_summary,
    list_value_declarations,
    record_value_declaration,
)
from apps.tasks.models import Task

pytestmark = pytest.mark.app_profile


def _uid() -> str:
    return str(uuid.uuid4())


def _task(db, user_id, *, status="completed", duration=0.0, time_spent=0.0, end=None):
    t = Task(
        name="t", status=status, duration=duration, time_spent=time_spent,
        user_id=uuid.UUID(user_id), end_time=end or datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    return t


class TestVolume:
    def test_effort_weighted_completed(self, db_session):
        uid = _uid()
        _task(db_session, uid, duration=10.0)   # 10 est-hours
        _task(db_session, uid, duration=30.0)   # 30 est-hours
        _task(db_session, uid, status="pending", duration=100.0)  # not completed -> ignored
        v = tas.compute_volume(db_session, uid)
        assert v["completed_count"] == 2
        assert v["effort_hours"] == pytest.approx(40.0)
        assert 0 < v["score"] <= 100

    def test_empty(self, db_session):
        v = tas.compute_volume(db_session, _uid())
        assert v["completed_count"] == 0
        assert v["score"] == 0.0


class TestTrajectory:
    def test_ahead_of_estimate_scores_above_neutral(self, db_session):
        uid = _uid()
        # estimated 10h, took 5h (18000s) -> 2x faster -> ratio capped 2 -> score 100
        _task(db_session, uid, duration=10.0, time_spent=5 * 3600)
        tr = tas.compute_trajectory(db_session, uid)
        assert tr["tasks_measured"] == 1
        assert tr["ahead"] == 1
        assert tr["score"] > 50  # ahead of plan

    def test_behind_estimate_scores_below_neutral(self, db_session):
        uid = _uid()
        # estimated 5h, took 10h -> half speed -> ratio 0.5 -> score 25
        _task(db_session, uid, duration=5.0, time_spent=10 * 3600)
        tr = tas.compute_trajectory(db_session, uid)
        assert tr["behind"] == 1
        assert tr["score"] < 50

    def test_on_time_is_neutral(self, db_session):
        uid = _uid()
        _task(db_session, uid, duration=4.0, time_spent=4 * 3600)  # exactly on estimate
        tr = tas.compute_trajectory(db_session, uid)
        assert tr["on_time"] == 1
        assert tr["score"] == pytest.approx(50.0, abs=1.0)

    def test_no_estimated_tasks(self, db_session):
        uid = _uid()
        _task(db_session, uid, duration=0.0, time_spent=3600)  # no estimate -> excluded
        tr = tas.compute_trajectory(db_session, uid)
        assert tr["score"] is None
        assert tr["tasks_measured"] == 0


class TestWorthDeclarations:
    def test_record_and_summary_by_kind(self, db_session):
        uid = _uid()
        record_value_declaration(db_session, user_id=uid, target_type="project",
                                 label="Nodus", declared_value=80.0, kind="intrinsic")
        record_value_declaration(db_session, user_id=uid, target_type="project",
                                 label="runtime", declared_value=40.0, kind="strategic")
        s = declared_worth_summary(db_session, uid)
        assert s["total"] == pytest.approx(120.0)
        assert s["by_kind"] == {"intrinsic": 80.0, "strategic": 40.0}
        assert s["count"] == 2

    def test_upsert_on_target(self, db_session):
        uid = _uid()
        record_value_declaration(db_session, user_id=uid, target_type="task",
                                 target_id="42", declared_value=10.0)
        out = record_value_declaration(db_session, user_id=uid, target_type="task",
                                       target_id="42", declared_value=25.0)
        assert out["created"] is False
        assert declared_worth_summary(db_session, uid)["total"] == pytest.approx(25.0)
        assert len(list_value_declarations(db_session, uid)) == 1

    def test_validation(self, db_session):
        uid = _uid()
        with pytest.raises(ValueError):
            record_value_declaration(db_session, user_id=uid, target_type="bogus", declared_value=1)
        with pytest.raises(ValueError):
            record_value_declaration(db_session, user_id=uid, target_type="task",
                                     declared_value=1, kind="bogus")

    def test_worth_axis_provisional_from_declared(self, db_session, monkeypatch):
        uid = _uid()
        monkeypatch.setattr(tas, "_realized_revenue", lambda db, u: 250.0)
        record_value_declaration(db_session, user_id=uid, target_type="project",
                                 declared_value=100.0, kind="monetary_potential")
        w = tas.compute_worth(db_session, uid)
        assert w["declared_total"] == pytest.approx(100.0)
        assert w["realized_revenue"] == 250.0        # shown raw, not folded into score
        assert 0 < w["score"] <= 100
        assert w["declared_by_kind"] == {"monetary_potential": 100.0}


class TestSnapshotAndInvariant:
    def test_snapshot_shape(self, db_session):
        uid = _uid()
        _task(db_session, uid, duration=8.0, time_spent=6 * 3600)
        snap = tas.compute_three_axes(db_session, uid)
        assert set(snap) >= {"volume", "worth", "trajectory", "master_score", "observability_only"}
        assert snap["observability_only"] is True
        assert "score" in snap["volume"] and "score" in snap["trajectory"]

    def test_never_writes_master_score(self, db_session):
        """The Phase-A invariant: computing the snapshot must not create/modify UserScore."""
        from apps.analytics.models import UserScore

        uid = _uid()
        _task(db_session, uid, duration=8.0, time_spent=4 * 3600)
        record_value_declaration(db_session, user_id=uid, target_type="project", declared_value=50.0)
        before = db_session.query(UserScore).filter(UserScore.user_id == uuid.UUID(uid)).count()
        tas.compute_three_axes(db_session, uid)
        after = db_session.query(UserScore).filter(UserScore.user_id == uuid.UUID(uid)).count()
        assert before == after == 0  # no UserScore row created by the snapshot
