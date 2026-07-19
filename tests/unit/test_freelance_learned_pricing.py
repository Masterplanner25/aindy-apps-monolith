"""Freelance learned pricing — the loop learns from REALIZED revenue.

The pricing loop applied changes on static satisfaction thresholds and never checked whether a
change actually improved revenue (`realized_revenue` was measured but ignored). This closes it:
each applied change is scored on expected revenue per lead (`baseline_price × acceptance_rate`)
vs its snapshot, a degraded change is auto-reverted, and the verdict feeds a per-service learned
revenue-direction bias that nudges the (previously static) multiplier. Covers the pure objective
+ learned bias, the gate blend, and the DB `evaluate_outcomes` path.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.freelance.models.freelance import ClientFeedback, FreelanceOrder
from apps.freelance.models.pricing import PricingRecommendation, ServicePrice
from apps.freelance.services.revenue_intelligence_service import (
    LEARN_WEIGHT,
    OBSERVATION_HOURS,
    RevenueIntelligenceService,
    _classify_outcome,
    _price_multiplier,
    _revenue_score,
    evaluate_pricing_gate,
    learned_revenue_bias,
)

pytestmark = pytest.mark.app_profile


# ── pure objective + learned bias ──────────────────────────────────────────────
def test_revenue_score_is_price_times_acceptance():
    assert _revenue_score({"baseline_price": 100.0, "acceptance_rate": 0.8}) == pytest.approx(80.0)
    assert _revenue_score({}) == pytest.approx(0.0)


def test_classify_outcome_relative():
    assert _classify_outcome(50.0, 80.0)[0] == "improved"    # +60%
    assert _classify_outcome(100.0, 80.0)[0] == "degraded"   # -20%
    assert _classify_outcome(100.0, 102.0)[0] == "neutral"   # +2% within deadband


def test_learned_bias_sign_and_min_outcomes():
    # under-priced signature: raising helped / lowering hurt -> positive bias
    assert learned_revenue_bias([("increase", "improved"), ("decrease", "degraded")]) == pytest.approx(1.0)
    # over-priced signature -> negative bias
    assert learned_revenue_bias([("increase", "degraded"), ("decrease", "improved")]) == pytest.approx(-1.0)
    # below the min-outcomes floor -> no learned opinion
    assert learned_revenue_bias([("increase", "improved")]) == pytest.approx(0.0)
    # neutral outcomes don't count
    assert learned_revenue_bias([("increase", "neutral"), ("decrease", "neutral")]) == pytest.approx(0.0)


def test_multiplier_blends_learned_bias():
    neutral = {"avg_rating": None, "refund_rate": 0.0, "acceptance_rate": 0.9}
    assert _price_multiplier(neutral, 0.0) == pytest.approx(1.0)
    assert _price_multiplier(neutral, 1.0) == pytest.approx(1.0 + LEARN_WEIGHT)
    assert _price_multiplier(neutral, -1.0) == pytest.approx(1.0 - LEARN_WEIGHT)


def test_gate_learned_bias_flips_a_hold_into_a_change():
    # neutral satisfaction signals alone -> hold; a positive learned bias moves it past the deadband.
    neutral = {"sample_size": 5, "baseline_price": 100.0, "avg_rating": None,
               "refund_rate": 0.0, "acceptance_rate": 0.9}
    held, _ = evaluate_pricing_gate({"web": neutral}, {"web": 100.0}, set())
    assert held == []                                  # static rule holds
    recs, _ = evaluate_pricing_gate({"web": neutral}, {"web": 100.0}, set(),
                                    learned_bias_by_service={"web": 1.0})
    assert len(recs) == 1 and recs[0]["direction"] == "increase"
    assert recs[0]["learned_bias"] == pytest.approx(1.0)


# ── evaluate_outcomes (DB integration) ─────────────────────────────────────────
def _seed_orders(db, uid, *, service_type="web", n, accepted, price=100.0, rating=5):
    now = datetime.now(timezone.utc)
    u = uuid.UUID(uid)
    for i in range(n):
        paid = i < accepted
        o = FreelanceOrder(client_name="C", client_email=f"c{i}@e.com", service_type=service_type,
                           price=price, status="delivered",
                           payment_confirmed_at=now if paid else None, user_id=u)
        db.add(o)
        db.flush()
        if paid and rating:
            db.add(ClientFeedback(order_id=o.id, rating=rating, user_id=u))
    db.commit()


def _seed_matured_rec(db, uid, *, service_type, snapshot, prior_price, applied_price, direction):
    u = uuid.UUID(uid)
    existing = db.query(ServicePrice).filter(
        ServicePrice.user_id == u, ServicePrice.service_type == service_type).first()
    if existing is None:
        db.add(ServicePrice(user_id=u, service_type=service_type, current_price=applied_price, source="auto"))
    rec = PricingRecommendation(
        user_id=u, service_type=service_type, sample_size=snapshot.get("sample_size"),
        baseline_price=snapshot.get("baseline_price"), recommended_price=applied_price,
        multiplier=1.1, direction=direction, rationale="seed", signals=snapshot,
        status="applied", prior_price=prior_price, trigger="manual",
        applied_at=datetime.now(timezone.utc) - timedelta(hours=OBSERVATION_HOURS + 1),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def test_outcome_improved_no_revert(db_session):
    uid = str(uuid.uuid4())
    _seed_orders(db_session, uid, n=10, accepted=8)   # current revenue_score = 100 × 0.8 = 80
    rec = _seed_matured_rec(db_session, uid, service_type="web",
                            snapshot={"sample_size": 5, "baseline_price": 100.0, "acceptance_rate": 0.5},  # score 50
                            prior_price=90.0, applied_price=100.0, direction="increase")
    summary = RevenueIntelligenceService(db_session, uid).evaluate_outcomes()
    assert summary["improved"] == 1 and summary["auto_reverted"] == 0
    reloaded = db_session.query(PricingRecommendation).get(rec.id)
    assert reloaded.outcome == "improved" and reloaded.status == "applied"


def test_outcome_degraded_auto_reverts(db_session):
    uid = str(uuid.uuid4())
    _seed_orders(db_session, uid, n=10, accepted=8)   # current revenue_score = 80
    rec = _seed_matured_rec(db_session, uid, service_type="web",
                            snapshot={"sample_size": 5, "baseline_price": 100.0, "acceptance_rate": 1.0},  # score 100
                            prior_price=90.0, applied_price=110.0, direction="increase")
    summary = RevenueIntelligenceService(db_session, uid).evaluate_outcomes()
    assert summary["degraded"] == 1 and summary["auto_reverted"] == 1
    reloaded = db_session.query(PricingRecommendation).get(rec.id)
    assert reloaded.outcome == "degraded" and reloaded.status == "reverted"
    # price restored to the pre-change value
    row = db_session.query(ServicePrice).filter(
        ServicePrice.user_id == uuid.UUID(uid), ServicePrice.service_type == "web").first()
    assert row.current_price == pytest.approx(90.0)


def test_learned_bias_reflects_recorded_outcomes(db_session):
    """After a degraded increase is recorded, the service is judged over-priced -> negative bias."""
    uid = str(uuid.uuid4())
    _seed_orders(db_session, uid, n=10, accepted=8)
    for _ in range(2):  # need >= LEARN_MIN_OUTCOMES
        _seed_matured_rec(db_session, uid, service_type="web",
                          snapshot={"sample_size": 5, "baseline_price": 100.0, "acceptance_rate": 1.0},
                          prior_price=90.0, applied_price=110.0, direction="increase")
    svc = RevenueIntelligenceService(db_session, uid)
    svc.evaluate_outcomes()   # records degraded outcomes (increase degraded)
    bias = svc._learned_bias_by_service().get("web", 0.0)
    assert bias < 0   # over-priced: increases degraded revenue -> lean price down


def test_unmatured_rec_not_evaluated(db_session):
    uid = str(uuid.uuid4())
    _seed_orders(db_session, uid, n=10, accepted=8)
    u = uuid.UUID(uid)
    db_session.add(PricingRecommendation(
        user_id=u, service_type="web", baseline_price=100.0, recommended_price=110.0,
        multiplier=1.1, direction="increase", signals={"baseline_price": 100.0, "acceptance_rate": 1.0},
        status="applied", prior_price=90.0, trigger="manual",
        applied_at=datetime.now(timezone.utc),   # fresh -> too young to judge
    ))
    db_session.commit()
    assert RevenueIntelligenceService(db_session, uid).evaluate_outcomes()["evaluated"] == 0
