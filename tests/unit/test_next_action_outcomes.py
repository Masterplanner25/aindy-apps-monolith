"""Next-Action dispatch-outcome read (FR-3 adoption).

Seeds the runtime ``system_events`` ledger with ``next_action.dispatched`` outcomes
(and their parent ``next_action.chosen``) and asserts the app read returns the
dispositions, the per-disposition summary, the CHOSEN->DISPATCHED chain, trace/user
scoping, and the acting-enabled hint — the observability used to soak autonomous acting.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from AINDY.core.system_event_types import SystemEventTypes
from AINDY.db.models.system_event import SystemEvent
from apps.agent.agents.next_action_outcomes import acting_enabled, get_dispatch_outcomes

pytestmark = pytest.mark.app_profile


def _uid() -> str:
    return str(uuid.uuid4())


def _add_event(db, *, user_id, type_, payload, trace_id=None, parent_id=None, ts=None):
    ev = SystemEvent(
        id=uuid.uuid4(),
        type=type_,
        user_id=uuid.UUID(user_id),
        trace_id=trace_id,
        parent_event_id=parent_id,
        source="agent",
        payload=payload,
        timestamp=ts or datetime.now(timezone.utc),
    )
    db.add(ev)
    db.flush()
    return ev


def _dispatched(disposition, **extra):
    return {"disposition": disposition, "dispatched": disposition == "dispatched", **extra}


class TestDispatchOutcomes:

    def test_empty_for_user_with_no_events(self, db_session):
        out = get_dispatch_outcomes(db_session, user_id=_uid())
        assert out["outcomes"] == []
        assert out["summary"] == {}
        assert out["count"] == 0

    def test_reads_disposition_and_summary(self, db_session):
        uid = _uid()
        base = datetime.now(timezone.utc)
        _add_event(db_session, user_id=uid, type_=SystemEventTypes.NEXT_ACTION_DISPATCHED,
                   payload=_dispatched("dispatched"), trace_id="t1", ts=base - timedelta(minutes=2))
        _add_event(db_session, user_id=uid, type_=SystemEventTypes.NEXT_ACTION_DISPATCHED,
                   payload=_dispatched("declined_admission", reason="not admitted"),
                   trace_id="t2", ts=base - timedelta(minutes=1))
        _add_event(db_session, user_id=uid, type_=SystemEventTypes.NEXT_ACTION_DISPATCHED,
                   payload=_dispatched("dispatched"), trace_id="t3", ts=base)

        out = get_dispatch_outcomes(db_session, user_id=uid)
        assert out["count"] == 3
        assert out["summary"] == {"dispatched": 2, "declined_admission": 1}
        # newest first
        assert out["outcomes"][0]["trace_id"] == "t3"
        assert out["outcomes"][1]["disposition"] == "declined_admission"
        assert out["outcomes"][1]["reason"] == "not admitted"

    def test_chain_joins_parent_chosen(self, db_session):
        uid = _uid()
        chosen = _add_event(
            db_session, user_id=uid, type_=SystemEventTypes.NEXT_ACTION_CHOSEN,
            payload={"action": "trigger_execution", "reason": "continue the plan"}, trace_id="tc",
        )
        _add_event(
            db_session, user_id=uid, type_=SystemEventTypes.NEXT_ACTION_DISPATCHED,
            payload=_dispatched("dispatched", followup_run_id="run-9", followup_status="completed"),
            trace_id="tc", parent_id=chosen.id,
        )
        out = get_dispatch_outcomes(db_session, user_id=uid)
        row = out["outcomes"][0]
        assert row["followup_run_id"] == "run-9"
        assert row["followup_status"] == "completed"
        assert row["chosen"]["action"] == "trigger_execution"
        assert row["chosen"]["reason"] == "continue the plan"
        assert row["chosen"]["event_id"] == str(chosen.id)

    def test_trace_filter(self, db_session):
        uid = _uid()
        _add_event(db_session, user_id=uid, type_=SystemEventTypes.NEXT_ACTION_DISPATCHED,
                   payload=_dispatched("dispatched"), trace_id="keep")
        _add_event(db_session, user_id=uid, type_=SystemEventTypes.NEXT_ACTION_DISPATCHED,
                   payload=_dispatched("declined_chain_depth"), trace_id="other")
        out = get_dispatch_outcomes(db_session, user_id=uid, trace_id="keep")
        assert out["count"] == 1
        assert out["outcomes"][0]["trace_id"] == "keep"

    def test_scoped_per_user(self, db_session):
        u1, u2 = _uid(), _uid()
        _add_event(db_session, user_id=u1, type_=SystemEventTypes.NEXT_ACTION_DISPATCHED,
                   payload=_dispatched("dispatched"))
        assert get_dispatch_outcomes(db_session, user_id=u2)["count"] == 0

    def test_only_reads_dispatched_not_chosen(self, db_session):
        uid = _uid()
        _add_event(db_session, user_id=uid, type_=SystemEventTypes.NEXT_ACTION_CHOSEN,
                   payload={"action": "trigger_execution"})
        # a CHOSEN with no DISPATCHED -> nothing in the outcome read
        assert get_dispatch_outcomes(db_session, user_id=uid)["count"] == 0

    def test_limit_capped(self, db_session):
        uid = _uid()
        for i in range(5):
            _add_event(db_session, user_id=uid, type_=SystemEventTypes.NEXT_ACTION_DISPATCHED,
                       payload=_dispatched("dispatched"), trace_id=f"t{i}")
        out = get_dispatch_outcomes(db_session, user_id=uid, limit=2)
        assert out["count"] == 2

    def test_acting_enabled_reflects_flag(self, db_session, monkeypatch):
        monkeypatch.delenv("AINDY_NEXT_ACTION_ACTING", raising=False)
        assert get_dispatch_outcomes(db_session, user_id=_uid())["acting_enabled"] is False
        assert acting_enabled() is False
        monkeypatch.setenv("AINDY_NEXT_ACTION_ACTING", "1")
        assert acting_enabled() is True
        assert get_dispatch_outcomes(db_session, user_id=_uid())["acting_enabled"] is True
