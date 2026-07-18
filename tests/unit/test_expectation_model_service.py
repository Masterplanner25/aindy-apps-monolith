"""
Unit tests for the shadow expectation model (Phase 0 learned recursion).

Covers the pure ridge math, the flag-gated shadow logging (drives nothing, no-op
when off), training (abstain below the sample floor, fit above), and the
learned-vs-heuristic evaluate report. Runs on sqlite via db_session.
"""
from __future__ import annotations

import itertools

import pytest

from apps.analytics.expectation_model import (
    InfinityExpectationModel,
    InfinityExpectationPrediction,
)
from apps.analytics.services.scoring import expectation_model_service as ems

pytestmark = pytest.mark.app_profile


# ── pure math ────────────────────────────────────────────────────────────────

def test_build_features_missing_and_suffix_fallback():
    feats = ems.build_features({"execution_speed": 80, "decision_efficiency_score": 60})
    assert feats[0] == 80.0
    assert feats[1] == 60.0   # via the *_score fallback
    assert feats[2] == 0.0    # missing -> 0.0
    assert len(feats) == len(ems.FEATURE_KEYS)


def test_ridge_recovers_linear_relation():
    # y = 1.0*f0 + 0.5*f1 + 0.25*f2 + 5 ; f3,f4 irrelevant. Full-rank grid.
    X, y = [], []
    for combo in itertools.product((0.0, 50.0, 100.0), repeat=5):
        X.append(list(combo))
        y.append(1.0 * combo[0] + 0.5 * combo[1] + 0.25 * combo[2] + 5.0)
    coefs = ems._fit_ridge(X, y, lam=1e-6)
    pred = ems._predict_coefs(coefs, [30.0, 40.0, 10.0, 0.0, 0.0])
    assert abs(pred - (30 + 20 + 2.5 + 5)) < 1.0


def test_predict_clamps_to_0_100():
    assert ems._predict_coefs([1000.0, 0, 0, 0, 0, 0], [100, 0, 0, 0, 0]) == 100.0
    assert ems._predict_coefs([-1000.0, 0, 0, 0, 0, 0], [100, 0, 0, 0, 0]) == 0.0


def test_mae():
    assert ems._mae([1, 2, 3], [1, 2, 3]) == 0.0
    assert ems._mae([2, 2], [0, 0]) == 2.0
    assert ems._mae([], []) is None


# ── flag gating ──────────────────────────────────────────────────────────────

def test_shadow_disabled_by_default(monkeypatch):
    monkeypatch.delenv(ems.SHADOW_FLAG_ENV, raising=False)
    assert ems.shadow_enabled() is False


def test_shadow_log_is_noop_when_off(db_session, monkeypatch):
    monkeypatch.delenv(ems.SHADOW_FLAG_ENV, raising=False)
    result = ems.shadow_log_expectation(
        db_session,
        loop_adjustment_id="a1",
        decision_type="review_plan",
        score_snapshot={"execution_speed": 50},
        heuristic_expected=55,
        actual_score=60,
    )
    assert result is None
    assert db_session.query(InfinityExpectationPrediction).count() == 0


# ── db-backed loop ───────────────────────────────────────────────────────────

def _snap(es=50, de=50, ai=50, fq=50, mp=50, master=50):
    return {
        "execution_speed": es, "decision_efficiency": de, "ai_productivity_boost": ai,
        "focus_quality": fq, "masterplan_progress": mp, "master_score": master,
    }


def test_shadow_log_writes_row_and_abstains_without_model(db_session, monkeypatch):
    monkeypatch.setenv(ems.SHADOW_FLAG_ENV, "1")
    result = ems.shadow_log_expectation(
        db_session,
        loop_adjustment_id="a1",
        decision_type="review_plan",
        score_snapshot=_snap(),
        heuristic_expected=53,
        actual_score=58,
    )
    assert result is not None
    row = db_session.query(InfinityExpectationPrediction).one()
    assert row.learned_expected is None       # no model yet -> abstain
    assert row.heuristic_expected == 53
    assert row.actual_score == 58
    assert len(row.features) == len(ems.FEATURE_KEYS)


def test_train_abstains_below_floor_then_fits(db_session, monkeypatch):
    monkeypatch.setenv(ems.SHADOW_FLAG_ENV, "1")

    # Below the floor -> skipped.
    for i in range(ems.MIN_TRAIN_SAMPLES - 1):
        db_session.add(InfinityExpectationPrediction(
            decision_type="review_plan", features=[float(i), 0, 0, 0, 0],
            actual_score=float(i) + 5, heuristic_expected=float(i),
        ))
    db_session.commit()
    summary = ems.train(db_session)
    assert summary["trained"] == []
    assert any("insufficient" in s["reason"] for s in summary["skipped"])

    # Enough rows with a clean linear relation actual = 1.0*f0 + 10 -> fits.
    db_session.query(InfinityExpectationPrediction).delete()
    db_session.commit()
    for i in range(ems.MIN_TRAIN_SAMPLES + 5):
        f0 = float((i * 4) % 100)
        db_session.add(InfinityExpectationPrediction(
            decision_type="review_plan", features=[f0, 0, 0, 0, 0],
            actual_score=1.0 * f0 + 10, heuristic_expected=f0,
        ))
    db_session.commit()

    summary = ems.train(db_session)
    assert any(t["decision_type"] == "review_plan" for t in summary["trained"])
    model = db_session.query(InfinityExpectationModel).filter_by(decision_type="review_plan").one()
    assert len(model.coefficients) == len(ems.FEATURE_KEYS) + 1
    pred = ems.predict_expected(db_session, "review_plan", [40.0, 0, 0, 0, 0])
    assert abs(pred - 50.0) < 3.0   # ~ 1.0*40 + 10


def test_evaluate_reports_learned_vs_heuristic(db_session, monkeypatch):
    monkeypatch.setenv(ems.SHADOW_FLAG_ENV, "1")
    # learned perfect, heuristic off by 10.
    for _ in range(5):
        db_session.add(InfinityExpectationPrediction(
            decision_type="review_plan", features=[50, 0, 0, 0, 0],
            learned_expected=60.0, heuristic_expected=50.0, actual_score=60.0,
        ))
    db_session.commit()

    report = ems.evaluate(db_session)
    dt = report["by_decision_type"]["review_plan"]
    assert dt["learned_mae"] == 0.0
    assert dt["heuristic_mae"] == 10.0
    assert dt["learned_wins"] is True
    assert report["overall"]["learned_wins"] is True


# ── Phase 1 advisory blend ───────────────────────────────────────────────────

def _put_model(db, decision_type, bias):
    """Insert a bias-only model so predict_expected returns a known value."""
    db.add(InfinityExpectationModel(
        decision_type=decision_type,
        coefficients=[0.0, 0.0, 0.0, 0.0, 0.0, float(bias)],
        feature_keys=list(ems.FEATURE_KEYS),
        feature_version=ems.FEATURE_VERSION,
        sample_size=50,
        holdout_mae=1.0,
    ))
    db.commit()


def test_advisory_off_returns_heuristic(db_session, monkeypatch):
    monkeypatch.delenv(ems.ADVISORY_FLAG_ENV, raising=False)
    _put_model(db_session, "review_plan", bias=70)  # a model exists, but flag is off
    effective, meta = ems.blended_expected_score(db_session, "review_plan", _snap(), 50.0)
    assert effective == 50.0
    assert meta["applied"] is False and meta["reason"] == "advisory_off"


def test_advisory_on_without_model_returns_heuristic(db_session, monkeypatch):
    monkeypatch.setenv(ems.ADVISORY_FLAG_ENV, "1")
    effective, meta = ems.blended_expected_score(db_session, "review_plan", _snap(), 50.0)
    assert effective == 50.0
    assert meta["applied"] is False and meta["reason"] == "no_model"


def test_advisory_blends_within_weight(db_session, monkeypatch):
    monkeypatch.setenv(ems.ADVISORY_FLAG_ENV, "1")
    _put_model(db_session, "review_plan", bias=70)  # learned = 70
    effective, meta = ems.blended_expected_score(db_session, "review_plan", _snap(), 50.0)
    assert meta["applied"] is True
    assert meta["learned_expected"] == 70.0
    assert effective == 56.0            # 50 + 0.3*(70-50)
    assert meta["shift"] == 6.0


def test_advisory_shift_is_bounded(db_session, monkeypatch):
    monkeypatch.setenv(ems.ADVISORY_FLAG_ENV, "1")
    _put_model(db_session, "review_plan", bias=200)  # predict clamps learned to 100
    effective, meta = ems.blended_expected_score(db_session, "review_plan", _snap(), 50.0)
    assert meta["learned_expected"] == 100.0
    assert effective == 50.0 + ems.ADVISORY_MAX_SHIFT   # bounded, not 0.3*50=15
    assert meta["shift"] == ems.ADVISORY_MAX_SHIFT
