"""
Unit tests for LeadExecutionService against a real (sqlite) session.

Drives the Search Execution Layer end-to-end: seed scored leads, then assert the
service selects, drafts, records, dedups, and reverts — the behavior that turns a
scored-but-idle lead into a tracked, acted-upon LeadAction.

Drafting is forced to the offline template (no LLM/network) so tests are hermetic.
"""
from __future__ import annotations

import uuid

import pytest

from apps.search.models.lead_action import LeadAction
from apps.search.models.leadgen_model import LeadGenResult
from apps.search.services.lead_execution_service import LeadExecutionService

pytestmark = pytest.mark.app_profile


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Force the deterministic template draft — never call the LLM in tests."""
    def _raise(item):
        raise RuntimeError("LLM disabled in tests")

    monkeypatch.setattr(LeadExecutionService, "_llm_draft", staticmethod(_raise))


def _seed_leads(db, user_id: str, specs: list[tuple[float, float]]) -> None:
    """specs: list of (overall_score, data_quality_score)."""
    db.add_all(
        [
            LeadGenResult(
                query="q",
                user_id=uuid.UUID(user_id),
                company=f"Co{i}",
                url="https://example.com",
                context="context",
                fit_score=overall,
                intent_score=overall,
                data_quality_score=dq,
                overall_score=overall,
                reasoning="r",
            )
            for i, (overall, dq) in enumerate(specs)
        ]
    )
    db.commit()


class TestLeadExecutionLoop:

    def test_dry_run_plan_does_not_persist(self, db_session):
        uid = str(uuid.uuid4())
        _seed_leads(db_session, uid, [(80, 90), (40, 90)])  # one qualifies, one below
        svc = LeadExecutionService(db=db_session, user_id=uid)

        plan = svc.plan()

        assert plan["would_act"] is True
        assert len(plan["selected"]) == 1
        assert svc.history() == []

    def test_execute_drafts_and_persists(self, db_session):
        uid = str(uuid.uuid4())
        _seed_leads(db_session, uid, [(80, 90), (75, 90)])
        svc = LeadExecutionService(db=db_session, user_id=uid)

        result = svc.execute()

        assert result["status"] == "executed"
        assert result["count"] == 2
        assert all(a["status"] == "drafted" for a in result["actions"])

        history = svc.history()
        assert len(history) == 2
        assert all(h["draft_body"] for h in history)      # a real draft exists
        assert all(h["decision_score"] >= 60 for h in history)

    def test_dedup_blocks_reaction(self, db_session):
        uid = str(uuid.uuid4())
        _seed_leads(db_session, uid, [(80, 90)])
        svc = LeadExecutionService(db=db_session, user_id=uid)

        assert svc.execute()["count"] == 1
        assert svc.execute()["status"] == "no_action"  # already actioned

    def test_revert_reenables_the_lead(self, db_session):
        uid = str(uuid.uuid4())
        _seed_leads(db_session, uid, [(80, 90)])
        svc = LeadExecutionService(db=db_session, user_id=uid)

        action_id = svc.execute()["actions"][0]["action_id"]
        assert svc.revert(action_id)["status"] == "reverted"
        # Reverted lead is eligible again.
        assert svc.execute()["count"] == 1

    def test_double_revert_is_idempotent(self, db_session):
        uid = str(uuid.uuid4())
        _seed_leads(db_session, uid, [(80, 90)])
        svc = LeadExecutionService(db=db_session, user_id=uid)

        action_id = svc.execute()["actions"][0]["action_id"]
        assert svc.revert(action_id)["status"] == "reverted"
        assert svc.revert(action_id)["status"] == "already_reverted"

    def test_revert_unknown_returns_not_found(self, db_session):
        svc = LeadExecutionService(db=db_session, user_id=str(uuid.uuid4()))
        assert svc.revert(999_999)["status"] == "not_found"
        assert svc.revert("not-an-int")["status"] == "not_found"

    def test_email_channel_queues_never_sends(self, db_session, monkeypatch):
        monkeypatch.delenv("AINDY_SEARCH_OUTREACH_SEND", raising=False)
        uid = str(uuid.uuid4())
        _seed_leads(db_session, uid, [(80, 90)])
        svc = LeadExecutionService(db=db_session, user_id=uid)

        result = svc.execute(channel="email")

        # Never 'sent' — the send channel is gated off and unwired.
        assert result["actions"][0]["status"] == "queued"
        record = svc.history()[0]
        assert record["status"] == "queued"
        assert "disabled" in (record["note"] or "")

    def test_below_threshold_leads_are_not_actioned(self, db_session):
        uid = str(uuid.uuid4())
        _seed_leads(db_session, uid, [(30, 90), (20, 90)])  # both below score gate
        svc = LeadExecutionService(db=db_session, user_id=uid)

        result = svc.execute()

        assert result["status"] == "no_action"
        assert result["count"] == 0
        assert svc.history() == []
