"""Genesis session creation is idempotent per user — starting Genesis resumes work in progress.

Regression: ``genesis_session_create_node`` created a new row on EVERY call. Navigating away
from Genesis and back therefore abandoned the in-progress session and started over. The
extracted ``summarized_state`` survived in the DB but became unreachable, and duplicate
``active`` rows accumulated per user (verified live: two POSTs produced session_id 7 then 8,
both ``status=active``).

Resuming must be scoped to *unfinished* work: a session that reached ``synthesized``,
``locked`` or ``abandoned`` is done, so starting Genesis again must create a fresh one —
otherwise a user could never begin a second plan.
"""
from __future__ import annotations

import uuid

import pytest

from apps.masterplan.flows.masterplan_flows import genesis_session_create_node
from apps.masterplan.models import GenesisSessionDB

pytestmark = pytest.mark.app_profile


def _run(db, user_id):
    return genesis_session_create_node({}, {"db": db, "user_id": str(user_id)})


def _session_id(result):
    return result["output_patch"]["genesis_session_create_result"]["session_id"]


def _result(result):
    return result["output_patch"]["genesis_session_create_result"]


def test_creates_a_session_when_none_exists(db_session):
    uid = uuid.uuid4()
    out = _run(db_session, uid)
    assert out["status"] == "SUCCESS"
    payload = _result(out)
    assert payload["session_id"] is not None
    assert payload["resumed"] is False


def test_second_call_resumes_instead_of_creating_a_duplicate(db_session):
    uid = uuid.uuid4()
    first = _session_id(_run(db_session, uid))
    second_out = _run(db_session, uid)

    assert _session_id(second_out) == first, "returning to Genesis must resume, not restart"
    assert _result(second_out)["resumed"] is True

    rows = (
        db_session.query(GenesisSessionDB)
        .filter(GenesisSessionDB.user_id == uid, GenesisSessionDB.status == "active")
        .all()
    )
    assert len(rows) == 1, "no duplicate active sessions may accumulate"


def test_resume_returns_the_work_already_done(db_session):
    """The point of resuming: the user gets their extracted plan state back."""
    uid = uuid.uuid4()
    sid = _session_id(_run(db_session, uid))

    row = db_session.query(GenesisSessionDB).filter(GenesisSessionDB.id == sid).first()
    row.summarized_state = {
        "vision_summary": "Run an AI consulting studio",
        "time_horizon": "5 years",
        "confidence": 0.4,
    }
    db_session.commit()

    payload = _result(_run(db_session, uid))
    assert payload["session_id"] == sid
    assert payload["summarized_state"]["vision_summary"] == "Run an AI consulting studio"
    assert payload["summarized_state"]["time_horizon"] == "5 years"


@pytest.mark.parametrize("finished_status", ["synthesized", "locked", "abandoned"])
def test_finished_sessions_do_not_block_starting_a_new_plan(db_session, finished_status):
    uid = uuid.uuid4()
    sid = _session_id(_run(db_session, uid))
    row = db_session.query(GenesisSessionDB).filter(GenesisSessionDB.id == sid).first()
    row.status = finished_status
    db_session.commit()

    payload = _result(_run(db_session, uid))
    assert payload["session_id"] != sid, f"a {finished_status} session must not be resumed"
    assert payload["resumed"] is False


def test_sessions_do_not_leak_across_users(db_session):
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    sid_a = _session_id(_run(db_session, user_a))
    payload_b = _result(_run(db_session, user_b))
    assert payload_b["session_id"] != sid_a
    assert payload_b["resumed"] is False
