"""IdentityService.observe — evidence-driven inference (rules -> probabilistic).

Asserts the behavioral shift: a single observation no longer flips a dimension; a value
is committed only after enough confident evidence accumulates, languages become preferred
only past a support threshold, and sustained counter-evidence revises a prior verdict.
"""

from __future__ import annotations

import uuid

import pytest

from apps.identity.models.identity_signal import IdentitySignal
from apps.identity.services.identity_service import IdentityService

pytestmark = pytest.mark.app_profile


def _uid() -> str:
    return str(uuid.uuid4())


def _svc(db, uid) -> IdentityService:
    return IdentityService(db=db, user_id=uid)


def _signal_count(db, uid) -> int:
    return db.query(IdentitySignal).filter(IdentitySignal.user_id == uuid.UUID(uid)).count()


class TestObserveRecordsEvidence:

    def test_single_observation_does_not_flip_dimension(self, db_session):
        uid = _uid()
        svc = _svc(db_session, uid)
        # one high-quality analysis: records evidence but must NOT commit (support 1 < 2)
        svc.observe("arm_analysis_complete", {"score": 9, "language": "python"})
        profile = svc.get_profile()
        assert profile["decision_making"]["speed_vs_quality"] is None  # not committed yet
        assert _signal_count(db_session, uid) == 2  # language + speed_vs_quality evidence

    def test_repeated_evidence_commits_dimension(self, db_session):
        uid = _uid()
        svc = _svc(db_session, uid)
        for _ in range(3):
            svc.observe("arm_analysis_complete", {"score": 9})
        assert svc.get_profile()["decision_making"]["speed_vs_quality"] == "quality"

    def test_language_needs_support_before_preferred(self, db_session):
        uid = _uid()
        svc = _svc(db_session, uid)
        svc.observe("arm_analysis_complete", {"language": "python", "score": 5})
        assert svc.get_profile()["tools"]["preferred_languages"] == []  # one signal, below support
        svc.observe("arm_generation_complete", {"language": "python"})
        assert svc.get_profile()["tools"]["preferred_languages"] == ["python"]  # now supported

    def test_masterplan_posture_commits_faster_with_stronger_weight(self, db_session):
        uid = _uid()
        svc = _svc(db_session, uid)
        # posture evidence weighs 1.5; two locks -> support 3.0, confident -> committed
        svc.observe("masterplan_locked", {"posture": "aggressive"})
        svc.observe("masterplan_locked", {"posture": "aggressive"})
        assert svc.get_profile()["decision_making"]["risk_tolerance"] == "aggressive"

    def test_counter_evidence_eventually_revises(self, db_session):
        uid = _uid()
        svc = _svc(db_session, uid)
        for _ in range(3):
            svc.observe("arm_analysis_complete", {"score": 9})   # -> quality
        assert svc.get_profile()["decision_making"]["speed_vs_quality"] == "quality"
        for _ in range(6):
            svc.observe("arm_analysis_complete", {"score": 3})   # sustained speed evidence
        assert svc.get_profile()["decision_making"]["speed_vs_quality"] == "speed"

    def test_unknown_event_records_nothing(self, db_session):
        uid = _uid()
        svc = _svc(db_session, uid)
        svc.observe("some_unrelated_event", {"foo": "bar"})
        assert _signal_count(db_session, uid) == 0

    def test_observation_count_increments_per_observation(self, db_session):
        uid = _uid()
        svc = _svc(db_session, uid)
        svc.observe("arm_analysis_complete", {"score": 9})
        svc.observe("arm_analysis_complete", {"score": 9})
        assert svc.get_profile()["evolution"]["observation_count"] == 2

    def test_commit_writes_evolution_log_with_confidence(self, db_session):
        uid = _uid()
        svc = _svc(db_session, uid)
        for _ in range(3):
            svc.observe("arm_analysis_complete", {"score": 9})
        summary = svc.get_evolution_summary()
        commits = [c for c in summary["recent_changes"] if c["dimension"] == "speed_vs_quality"]
        assert commits and commits[-1]["trigger"].startswith("inferred:")
        assert "confidence" in commits[-1]


class TestInferenceSummary:

    def test_summary_exposes_evidence_and_confidence(self, db_session):
        uid = _uid()
        svc = _svc(db_session, uid)
        for _ in range(3):
            svc.observe("arm_analysis_complete", {"score": 9, "language": "python"})
        summary = svc.get_inference_summary()

        sq = next(d for d in summary["dimensions"] if d["dimension"] == "speed_vs_quality")
        assert sq["inferred"] == "quality"
        assert sq["current"] == "quality"        # committed
        assert sq["confidence"] >= 0.6
        assert "quality" in sq["distribution"]

        assert summary["languages"]["inferred"] == ["python"]
        assert summary["languages"]["evidence"]["python"] >= 2.0
