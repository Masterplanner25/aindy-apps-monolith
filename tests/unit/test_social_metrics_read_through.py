"""
Social profile metrics are a read-through projection of analytics (SOCIAL-IDENTITY-1).

The analytics-owned scores (infinity_score = master_score, execution_speed_score) are
projected live from apps.analytics.public at serve time instead of being duplicated
into the Mongo profile by task completion. Social/task-owned fields (twr_score,
trust_score, execution_velocity) are left untouched.

Hermetic: the analytics lookup is monkeypatched; no DB/Mongo.
"""
from __future__ import annotations

import pytest

import apps.analytics.public as analytics_public
from apps.social.routes.social_router import _project_profile_metrics

pytestmark = pytest.mark.app_profile


def _profile(**snapshot):
    base = {"twr_score": 3.0, "trust_score": 50.0, "execution_velocity": 9.0, "infinity_score": 0.0}
    base.update(snapshot)
    return {"user_id": "11111111-1111-1111-1111-111111111111", "username": "x", "metrics_snapshot": base}


def test_projects_analytics_scores_over_stored(monkeypatch):
    monkeypatch.setattr(
        analytics_public, "get_user_score",
        lambda user_id, db: {"master_score": 72.0, "execution_speed_score": 61.0},
    )
    profile = _profile()
    out = _project_profile_metrics(profile, object())
    snap = out["metrics_snapshot"]

    # analytics-owned -> projected live
    assert snap["infinity_score"] == 72.0
    assert snap["execution_speed_score"] == 61.0
    # social/task-owned -> untouched
    assert snap["twr_score"] == 3.0
    assert snap["trust_score"] == 50.0
    assert snap["execution_velocity"] == 9.0
    # input not mutated
    assert profile["metrics_snapshot"]["infinity_score"] == 0.0


def test_no_user_id_returns_unchanged():
    profile = {"username": "x", "metrics_snapshot": {"trust_score": 50.0}}
    assert _project_profile_metrics(profile, object()) is profile


def test_missing_analytics_score_keeps_stored(monkeypatch):
    monkeypatch.setattr(analytics_public, "get_user_score", lambda user_id, db: None)
    profile = _profile(infinity_score=5.0)
    assert _project_profile_metrics(profile, object()) is profile


def test_analytics_failure_is_best_effort(monkeypatch):
    def _boom(user_id, db):
        raise RuntimeError("analytics unavailable")

    monkeypatch.setattr(analytics_public, "get_user_score", _boom)
    profile = _profile(infinity_score=5.0)
    assert _project_profile_metrics(profile, object()) is profile


def test_non_dict_returned_as_is():
    assert _project_profile_metrics(None, object()) is None
