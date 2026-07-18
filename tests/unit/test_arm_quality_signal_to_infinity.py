"""
ARM analysis-quality signal is the single source of truth for the ARM-derived
Infinity KPIs (was: analytics re-parsed ARM's result_full schema itself).

Covers the ARM-domain signal computation and that Infinity's ai_productivity_boost
and decision_efficiency KPIs consume it end-to-end. Hermetic (sqlite db_session).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import apps.analytics.services.scoring.infinity_service as infs
from apps.arm.models import AnalysisResult
from apps.arm.services.arm_metrics_service import analysis_quality_signals

pytestmark = pytest.mark.app_profile

_EMPTY = {
    "usage_count": 0,
    "quality_avg": 5.0,
    "quality_earliest": 5.0,
    "quality_latest": 5.0,
    "quality_trend": 0.0,
}


def _seed(db, user_id: str, *, arch, integ, days_ago, status="success", result_full=None):
    db.add(
        AnalysisResult(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            status=status,
            result_full=result_full if result_full is not None
            else json.dumps({"architecture_score": arch, "integrity_score": integ}),
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
    )


# ── ARM domain: the signal ────────────────────────────────────────────────────

class TestAnalysisQualitySignals:

    def test_empty_returns_defaults(self, db_session):
        sig = analysis_quality_signals(db_session, str(uuid.uuid4()), window_days=30)
        assert sig == _EMPTY

    def test_aggregates_avg_and_trend_ascending(self, db_session):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, arch=4, integ=4, days_ago=3)   # oldest -> avg 4
        _seed(db_session, uid, arch=6, integ=6, days_ago=2)   # avg 6
        _seed(db_session, uid, arch=8, integ=8, days_ago=1)   # newest -> avg 8
        db_session.commit()

        sig = analysis_quality_signals(db_session, uid, window_days=30)
        assert sig["usage_count"] == 3
        assert sig["quality_avg"] == 6.0
        assert sig["quality_earliest"] == 4.0
        assert sig["quality_latest"] == 8.0
        assert sig["quality_trend"] == 4.0

    def test_excludes_failed_and_out_of_window(self, db_session):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, arch=9, integ=9, days_ago=1, status="failed")  # excluded
        _seed(db_session, uid, arch=2, integ=2, days_ago=99)                  # out of window
        _seed(db_session, uid, arch=7, integ=7, days_ago=1)                   # included
        db_session.commit()

        sig = analysis_quality_signals(db_session, uid, window_days=30)
        assert sig["usage_count"] == 1
        assert sig["quality_avg"] == 7.0

    def test_unparsable_result_defaults_to_five(self, db_session):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, arch=0, integ=0, days_ago=1, result_full="not-json")
        db_session.commit()

        sig = analysis_quality_signals(db_session, uid, window_days=30)
        assert sig["usage_count"] == 1
        assert sig["quality_avg"] == 5.0


# ── analytics: Infinity consumes the signal ───────────────────────────────────

class TestInfinityConsumesArmSignal:

    def test_ai_productivity_boost_uses_arm_signal(self, db_session):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, arch=4, integ=4, days_ago=3)   # earliest 4
        _seed(db_session, uid, arch=8, integ=8, days_ago=1)   # latest 8 -> trend +4
        db_session.commit()

        score, data_points = infs.calculate_ai_productivity_boost(uid, db_session)

        expected = round(
            infs._sigmoid_score(2, 5.0, steepness=0.5) * 0.5
            + infs._normalize(4.0, -5.0, 5.0) * 0.5,
            2,
        )
        assert data_points == 2
        assert score == min(100.0, expected)

    def test_decision_efficiency_uses_arm_signal(self, db_session, monkeypatch):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, arch=6, integ=6, days_ago=1)   # quality_avg 6.0
        db_session.commit()
        monkeypatch.setattr(infs, "_get_user_tasks_for_scoring", lambda user_id, db: [])

        score, data_points = infs.calculate_decision_efficiency(uid, db_session)

        # completion_rate 0.5 (no tasks) * 60 + (6.0/10) * 40 = 30 + 24 = 54.0
        assert score == 54.0
        assert data_points == 1  # usage_count 1 + 0 tasks
