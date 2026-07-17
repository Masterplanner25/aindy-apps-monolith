"""
Unit tests for ARMAutoTuneService against a real (sqlite) session.

Drives the closed Reflect -> Adjust loop end-to-end: seed failing ARM sessions so
the suggestion engine emits low-risk changes, then assert the service applies,
audits, and reverts them — the behavior that turns auto_apply_safe from advisory
into acted-upon.
"""
from __future__ import annotations

import uuid

import pytest

from apps.arm.dao import arm_config_dao
from apps.arm.models import AnalysisResult
from apps.arm.services.arm_autotune_service import (
    AUTO_TUNE_ALLOWED_KEYS,
    ARMAutoTuneService,
)

pytestmark = pytest.mark.app_profile


def _seed_failing_sessions(db, user_id: str, n: int = 6) -> None:
    """n failed analyses -> 0% decision efficiency + 100% waste (low-risk triggers)."""
    db.add_all(
        [
            AnalysisResult(
                id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                user_id=uuid.UUID(user_id),
                status="failed",
                input_tokens=100,
                output_tokens=200,
                execution_seconds=1.0,
            )
            for _ in range(n)
        ]
    )
    db.commit()


class TestAutoTuneServiceLoop:

    def test_dry_run_plan_does_not_persist(self, db_session):
        uid = str(uuid.uuid4())
        _seed_failing_sessions(db_session, uid)
        svc = ARMAutoTuneService(db=db_session, user_id=uid)

        plan = svc.plan()

        assert plan["would_change"] is True
        assert plan["applied"], "expected at least one low-risk change to be planned"
        # Dry run writes nothing.
        assert arm_config_dao.get_config(db_session, user_id=uid) is None
        assert svc.history() == []

    def test_apply_persists_config_and_writes_audit(self, db_session):
        uid = str(uuid.uuid4())
        _seed_failing_sessions(db_session, uid)
        svc = ARMAutoTuneService(db=db_session, user_id=uid)

        result = svc.apply()

        assert result["status"] == "applied"
        assert result["applied"]
        assert all(c["param"] in AUTO_TUNE_ALLOWED_KEYS for c in result["applied"])

        row = arm_config_dao.get_config(db_session, user_id=uid)
        assert row is not None
        for change in result["applied"]:
            assert getattr(row, change["param"]) == change["new"]

        history = svc.history()
        assert len(history) == 1
        assert history[0]["reverted"] is False
        assert history[0]["applied"] == result["applied"]

    def test_revert_restores_prior_config(self, db_session):
        uid = str(uuid.uuid4())
        _seed_failing_sessions(db_session, uid)
        svc = ARMAutoTuneService(db=db_session, user_id=uid)

        applied = svc.apply()
        rev = svc.revert(applied["log_id"])

        assert rev["status"] == "reverted"
        row = arm_config_dao.get_config(db_session, user_id=uid)
        for change in applied["applied"]:
            assert getattr(row, change["param"]) == change["old"]
        assert svc.history()[0]["reverted"] is True

    def test_double_revert_is_idempotent(self, db_session):
        uid = str(uuid.uuid4())
        _seed_failing_sessions(db_session, uid)
        svc = ARMAutoTuneService(db=db_session, user_id=uid)

        log_id = svc.apply()["log_id"]
        assert svc.revert(log_id)["status"] == "reverted"
        assert svc.revert(log_id)["status"] == "already_reverted"

    def test_revert_unknown_id_returns_not_found(self, db_session):
        svc = ARMAutoTuneService(db=db_session, user_id=str(uuid.uuid4()))
        assert svc.revert(str(uuid.uuid4()))["status"] == "not_found"

    def test_min_sessions_gate_blocks_apply(self, db_session):
        uid = str(uuid.uuid4())
        _seed_failing_sessions(db_session, uid, n=2)  # below MIN_SESSIONS
        svc = ARMAutoTuneService(db=db_session, user_id=uid)

        result = svc.apply()

        assert result["status"] == "no_change"
        assert result["applied"] == []
        assert svc.history() == []

    def test_cooldown_blocks_immediate_reapply(self, db_session):
        uid = str(uuid.uuid4())
        _seed_failing_sessions(db_session, uid)
        svc = ARMAutoTuneService(db=db_session, user_id=uid)

        assert svc.apply()["status"] == "applied"
        # Same keys within the cooldown window -> nothing left to change.
        assert svc.apply()["status"] == "no_change"
