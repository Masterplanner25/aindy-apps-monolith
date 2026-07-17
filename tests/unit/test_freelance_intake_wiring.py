"""
Unit tests for the two consumption wires (real sqlite session):

  1. New orders default their price from the ServicePrice catalog (Revenue
     Intelligence Loop -> ServicePrice -> future orders).
  2. Freelance consumes Search's actioned leads (LeadAction) and converts them,
     completing the lead -> outreach -> client -> priced-order chain.
"""
from __future__ import annotations

import uuid

import pytest

from apps.freelance.models.pricing import ServicePrice
from apps.freelance.schemas.freelance import FreelanceOrderCreate
from apps.freelance.services import freelance_service, intake_service
from apps.freelance.services.freelance_service import _resolve_effective_price
from apps.search.models.lead_action import LeadAction
from apps.search.models.leadgen_model import LeadGenResult

pytestmark = pytest.mark.app_profile


def _seed_service_price(db, user_id: str, service_type: str, price: float) -> None:
    db.add(ServicePrice(user_id=uuid.UUID(user_id), service_type=service_type, current_price=price, source="auto"))
    db.commit()


def _order_create(service_type="web", price=0.0) -> FreelanceOrderCreate:
    return FreelanceOrderCreate(
        client_name="Acme", client_email="buyer@acme.com", service_type=service_type, price=price
    )


class TestDefaultPriceFromCatalog:

    def test_resolve_uses_catalog_when_price_zero(self, db_session):
        uid = str(uuid.uuid4())
        _seed_service_price(db_session, uid, "web", 250.0)
        assert _resolve_effective_price(db_session, uid, _order_create(price=0.0)) == 250.0

    def test_resolve_keeps_explicit_price(self, db_session):
        uid = str(uuid.uuid4())
        _seed_service_price(db_session, uid, "web", 250.0)
        assert _resolve_effective_price(db_session, uid, _order_create(price=99.0)) == 99.0

    def test_resolve_no_catalog_keeps_original(self, db_session):
        uid = str(uuid.uuid4())
        assert _resolve_effective_price(db_session, uid, _order_create(price=0.0)) == 0.0

    def test_create_order_defaults_price_from_catalog(self, db_session):
        uid = str(uuid.uuid4())
        _seed_service_price(db_session, uid, "web", 250.0)
        order = freelance_service.create_order(db_session, _order_create(price=0.0), user_id=uid)
        assert order.price == 250.0

    def test_create_order_respects_explicit_price(self, db_session):
        uid = str(uuid.uuid4())
        _seed_service_price(db_session, uid, "web", 250.0)
        order = freelance_service.create_order(db_session, _order_create(price=120.0), user_id=uid)
        assert order.price == 120.0


def _seed_lead_action(db, user_id: str, company="Acme", score=80):
    lead = LeadGenResult(
        query="q",
        user_id=uuid.UUID(user_id),
        company=company,
        url="https://acme.com",
        context="ctx",
        fit_score=score,
        intent_score=score,
        data_quality_score=90,
        overall_score=score,
        reasoning="r",
    )
    db.add(lead)
    db.flush()
    action = LeadAction(
        user_id=uuid.UUID(user_id),
        lead_id=lead.id,
        company=company,
        url="https://acme.com",
        channel="draft",
        status="drafted",
        draft_subject="Hi",
        draft_body="body",
    )
    db.add(action)
    db.commit()
    return lead, action


class TestActionedLeadConsumption:

    def test_list_actioned_leads(self, db_session):
        uid = str(uuid.uuid4())
        lead, action = _seed_lead_action(db_session, uid)
        rows = intake_service.list_actioned_leads(db_session, uid)
        assert len(rows) == 1
        assert rows[0]["action_id"] == action.id
        assert rows[0]["lead_id"] == lead.id
        assert rows[0]["company"] == "Acme"

    def test_convert_actioned_lead_creates_order(self, db_session):
        uid = str(uuid.uuid4())
        lead, action = _seed_lead_action(db_session, uid)
        result = intake_service.convert_actioned_lead(
            db_session, uid, action_id=action.id, client_email="buyer@acme.com", service_type="web"
        )
        assert result["action_id"] == action.id
        assert result["lead_id"] == lead.id
        assert result["order"].service_type == "web"
        assert result["order"].client_email == "buyer@acme.com"

    def test_convert_actioned_lead_uses_catalog_price(self, db_session):
        """Full chain: actioned lead -> convert -> create_order -> catalog default."""
        uid = str(uuid.uuid4())
        _seed_service_price(db_session, uid, "web", 250.0)
        _lead, action = _seed_lead_action(db_session, uid)
        result = intake_service.convert_actioned_lead(
            db_session, uid, action_id=action.id, client_email="buyer@acme.com", service_type="web"
        )
        assert result["order"].price == 250.0

    def test_convert_unknown_action_raises(self, db_session):
        uid = str(uuid.uuid4())
        with pytest.raises(ValueError):
            intake_service.convert_actioned_lead(
                db_session, uid, action_id=999999, client_email="x@y.com", service_type="web"
            )
