"""Search Execution learning close — the loop learns whether actioned leads convert.

The static gate only trusted overall_score + data_quality; it never checked whether actioned
leads actually convert, so leadgen could keep feeding a non-converting query and execution
would keep drafting outreach forever. This closes it: after an observation window each matured,
non-reverted action is judged on its in-domain conversion signal (a `convert`/thumbs_up on the
lead's url in SearchResultFeedback); a segment (leadgen query) that consistently fails to
convert is AUTO-SUPPRESSED forward — future leads from it are gated out (outreach can't be
un-sent, so we suppress rather than revert).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.search.models.lead_action import LeadAction
from apps.search.models.leadgen_model import LeadGenResult
from apps.search.models.result_feedback import SearchResultFeedback
from apps.search.services.lead_execution_service import (
    OBSERVATION_HOURS,
    SUPPRESS_MIN_OUTCOMES,
    LeadExecutionService,
    evaluate_lead_action_gate,
)

pytestmark = pytest.mark.app_profile


# ── gate: auto-suppress ─────────────────────────────────────────────────────────
def _lead(lead_id, score=80, dq=90, query="q"):
    return {"id": lead_id, "company": f"Co{lead_id}", "url": "https://example.com",
            "context": "c", "query": query, "overall_score": score, "data_quality_score": dq}


def test_gate_suppresses_low_conversion_segment():
    selected, skipped = evaluate_lead_action_gate(
        [_lead(1, query="deadquery")], set(), suppressed_segments={"deadquery"})
    assert selected == []
    assert "auto-suppressed" in skipped[0]["reason"]


def test_gate_passes_unsuppressed_segment():
    selected, _ = evaluate_lead_action_gate(
        [_lead(1, query="goodquery")], set(), suppressed_segments={"deadquery"})
    assert len(selected) == 1
    assert selected[0]["query"] == "goodquery"


# ── evaluate_outcomes (DB integration) ─────────────────────────────────────────
def _seed_lead(db, uid, *, company, url, query="q", score=80):
    lead = LeadGenResult(query=query, user_id=uuid.UUID(uid), company=company, url=url,
                         context="c", fit_score=score, intent_score=score,
                         data_quality_score=90, overall_score=score, reasoning="r")
    db.add(lead)
    db.flush()
    return lead


def _seed_matured_action(db, uid, *, company, url, query, converted, age_hours=OBSERVATION_HOURS + 1):
    u = uuid.UUID(uid)
    action = LeadAction(user_id=u, company=company, url=url, lead_query=query,
                        channel="draft", status="drafted", draft_subject="s", draft_body="b",
                        decision_score=80.0, decision_reason="qualified", trigger="manual")
    db.add(action)
    db.flush()
    # backdate created_at past the observation window so it's judged
    action.created_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    if converted:
        db.add(SearchResultFeedback(user_id=u, query=query, result_ref=url,
                                    kind="implicit", signal="convert", weight=1.0))
    db.commit()
    return action


def test_converted_action_is_judged_converted(db_session):
    uid = str(uuid.uuid4())
    a = _seed_matured_action(db_session, uid, company="Co1", url="https://a.com",
                             query="q", converted=True)
    summary = LeadExecutionService(db=db_session, user_id=uid).evaluate_outcomes()
    assert summary["evaluated"] == 1 and summary["converted"] == 1
    assert db_session.query(LeadAction).get(a.id).outcome == "converted"


def test_no_signal_action_is_judged_no_response(db_session):
    uid = str(uuid.uuid4())
    a = _seed_matured_action(db_session, uid, company="Co1", url="https://a.com",
                             query="q", converted=False)
    summary = LeadExecutionService(db=db_session, user_id=uid).evaluate_outcomes()
    assert summary["evaluated"] == 1 and summary["no_response"] == 1
    assert db_session.query(LeadAction).get(a.id).outcome == "no_response"


def test_fresh_action_not_evaluated(db_session):
    uid = str(uuid.uuid4())
    _seed_matured_action(db_session, uid, company="Co1", url="https://a.com",
                         query="q", converted=False, age_hours=1)  # too young
    assert LeadExecutionService(db=db_session, user_id=uid).evaluate_outcomes()["evaluated"] == 0


def test_reverted_action_not_evaluated(db_session):
    uid = str(uuid.uuid4())
    a = _seed_matured_action(db_session, uid, company="Co1", url="https://a.com",
                             query="q", converted=False)
    a.status = "reverted"
    db_session.commit()
    assert LeadExecutionService(db=db_session, user_id=uid).evaluate_outcomes()["evaluated"] == 0


def test_evaluate_outcomes_is_idempotent(db_session):
    uid = str(uuid.uuid4())
    _seed_matured_action(db_session, uid, company="Co1", url="https://a.com",
                         query="q", converted=True)
    svc = LeadExecutionService(db=db_session, user_id=uid)
    assert svc.evaluate_outcomes()["evaluated"] == 1
    assert svc.evaluate_outcomes()["evaluated"] == 0  # already has a verdict


# ── the close: judged non-conversion auto-suppresses the segment ────────────────
def test_dead_segment_gets_auto_suppressed(db_session):
    uid = str(uuid.uuid4())
    for i in range(SUPPRESS_MIN_OUTCOMES):   # enough non-converting actions to trust the verdict
        _seed_matured_action(db_session, uid, company=f"Co{i}", url=f"https://a{i}.com",
                             query="deadquery", converted=False)
    svc = LeadExecutionService(db=db_session, user_id=uid)
    summary = svc.evaluate_outcomes()
    assert "deadquery" in summary["suppressed_segments"]
    assert "deadquery" in svc._suppressed_segments()


def test_converting_segment_not_suppressed(db_session):
    uid = str(uuid.uuid4())
    for i in range(SUPPRESS_MIN_OUTCOMES):
        _seed_matured_action(db_session, uid, company=f"Co{i}", url=f"https://a{i}.com",
                             query="goodquery", converted=True)
    svc = LeadExecutionService(db=db_session, user_id=uid)
    svc.evaluate_outcomes()
    assert svc._suppressed_segments() == set()


def test_execute_gates_out_a_suppressed_segment_end_to_end(db_session):
    """After a dead segment is judged, a fresh high-score lead from it is not actioned."""
    uid = str(uuid.uuid4())
    for i in range(SUPPRESS_MIN_OUTCOMES):
        _seed_matured_action(db_session, uid, company=f"Co{i}", url=f"https://a{i}.com",
                             query="deadquery", converted=False)
    # a brand-new, well-scored lead — but from the proven-dead segment
    _seed_lead(db_session, uid, company="NewCo", url="https://new.com", query="deadquery", score=95)
    db_session.commit()

    result = LeadExecutionService(db=db_session, user_id=uid).execute()  # runs evaluate_outcomes first
    assert result["status"] == "no_action"
    assert "deadquery" in result["suppressed_segments"]
    assert any("auto-suppressed" in s["reason"] for s in result["skipped"])
