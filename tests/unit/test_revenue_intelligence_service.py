"""
Unit tests for RevenueIntelligenceService against a real (sqlite) session.

Drives the Revenue Intelligence Loop end-to-end: seed paid orders + client feedback,
then assert the service recommends, applies (writes the default-price catalog +
records an audit), and reverts — the behavior that turns idle feedback/revenue into
an acted-upon pricing decision.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from apps.freelance.models.freelance import ClientFeedback, FreelanceOrder
from apps.freelance.models.pricing import ServicePrice
from apps.freelance.services.revenue_intelligence_service import (
    RevenueIntelligenceService,
    get_service_price,
)

pytestmark = pytest.mark.app_profile


def _seed(db, user_id: str, *, service_type="web", n=5, price=100.0, rating=5, refunded=0):
    now = datetime.now(timezone.utc)
    uid = uuid.UUID(user_id)
    orders = []
    for i in range(n):
        order = FreelanceOrder(
            client_name="Client",
            client_email=f"c{i}@example.com",
            service_type=service_type,
            price=price,
            status="delivered",
            payment_confirmed_at=now,   # paid -> counts toward sample
            user_id=uid,
        )
        db.add(order)
        db.flush()
        orders.append(order)
        db.add(ClientFeedback(order_id=order.id, rating=rating, user_id=uid))
    for i in range(refunded):
        orders[i].refunded_at = now
    db.commit()
    return orders


class TestRevenueIntelligenceLoop:

    def test_dry_run_plan_does_not_persist(self, db_session):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, rating=5)
        svc = RevenueIntelligenceService(db=db_session, user_id=uid)

        plan = svc.plan()

        assert plan["would_change"] is True
        assert plan["recommendations"][0]["direction"] == "increase"
        assert svc.history() == []
        assert svc.catalog() == []

    def test_apply_writes_catalog_and_audit(self, db_session):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, rating=5, price=100.0)
        svc = RevenueIntelligenceService(db=db_session, user_id=uid)

        result = svc.apply()

        assert result["status"] == "applied"
        assert result["count"] == 1
        applied = result["applied"][0]
        assert applied["service_type"] == "web"
        assert applied["prior_price"] is None       # no default price existed before
        assert applied["recommended_price"] > 100.0

        # Catalog now carries the applied default price.
        assert get_service_price(db_session, uid, "web") == applied["recommended_price"]
        catalog = svc.catalog()
        assert catalog[0]["current_price"] == applied["recommended_price"]
        assert catalog[0]["source"] == "auto"

        history = svc.history()
        assert len(history) == 1
        assert history[0]["status"] == "applied"

    def test_revert_removes_price_when_none_existed(self, db_session):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, rating=5)
        svc = RevenueIntelligenceService(db=db_session, user_id=uid)

        rec_id = svc.apply()["applied"][0]["recommendation_id"]
        assert svc.revert(rec_id)["status"] == "reverted"
        # Prior was None -> the catalog row we added is removed.
        assert get_service_price(db_session, uid, "web") is None
        assert svc.history()[0]["status"] == "reverted"

    def test_revert_restores_prior_price(self, db_session):
        uid = str(uuid.uuid4())
        db_session.add(
            ServicePrice(user_id=uuid.UUID(uid), service_type="web", current_price=150.0, source="manual")
        )
        db_session.commit()
        _seed(db_session, uid, rating=5, price=100.0)
        svc = RevenueIntelligenceService(db=db_session, user_id=uid)

        applied = svc.apply()["applied"][0]
        assert applied["prior_price"] == 150.0
        assert applied["recommended_price"] > 150.0     # baseline is the current price, not history

        svc.revert(applied["recommendation_id"])
        assert get_service_price(db_session, uid, "web") == 150.0

    def test_cooldown_blocks_immediate_reapply(self, db_session):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, rating=5)
        svc = RevenueIntelligenceService(db=db_session, user_id=uid)

        assert svc.apply()["status"] == "applied"
        assert svc.apply()["status"] == "no_change"     # priced within cooldown window

    def test_double_revert_is_idempotent(self, db_session):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, rating=5)
        svc = RevenueIntelligenceService(db=db_session, user_id=uid)

        rec_id = svc.apply()["applied"][0]["recommendation_id"]
        assert svc.revert(rec_id)["status"] == "reverted"
        assert svc.revert(rec_id)["status"] == "already_reverted"

    def test_revert_unknown_returns_not_found(self, db_session):
        svc = RevenueIntelligenceService(db=db_session, user_id=str(uuid.uuid4()))
        assert svc.revert(999_999)["status"] == "not_found"
        assert svc.revert("not-an-int")["status"] == "not_found"

    def test_insufficient_sample_no_change(self, db_session):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, n=2, rating=5)   # below MIN_SAMPLE_SIZE
        svc = RevenueIntelligenceService(db=db_session, user_id=uid)

        assert svc.apply()["status"] == "no_change"
        assert svc.catalog() == []

    def test_poor_outcomes_recommend_decrease(self, db_session):
        uid = str(uuid.uuid4())
        _seed(db_session, uid, rating=2, price=100.0, refunded=2)
        svc = RevenueIntelligenceService(db=db_session, user_id=uid)

        applied = svc.apply()["applied"][0]
        assert applied["direction"] == "decrease"
        assert applied["recommended_price"] < 100.0
