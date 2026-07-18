"""
Unit tests for the Search result-feedback service (Search v4 outcome signal).

Drives capture + aggregation against a real (sqlite) session: implicit and explicit
signals, per-(user, query, result_ref, signal) dedup, explicit latest-vote-wins, the
blended per-query weight, and input validation.
"""
from __future__ import annotations

import uuid

import pytest

from apps.search.models.result_feedback import SearchResultFeedback
from apps.search.services.feedback_service import (
    SIGNAL_WEIGHTS,
    get_result_outcome_weights,
    record_feedback,
)

pytestmark = pytest.mark.app_profile


def _uid() -> str:
    return str(uuid.uuid4())


def _count(db, uid) -> int:
    return (
        db.query(SearchResultFeedback)
        .filter(SearchResultFeedback.user_id == uuid.UUID(uid))
        .count()
    )


class TestRecordFeedback:

    def test_implicit_click_recorded(self, db_session):
        uid = _uid()
        out = record_feedback(db_session, user_id=uid, query="ai crm", result_ref="r1", signal="click")
        assert out == {
            "recorded": True, "created": True, "result_ref": "r1",
            "signal": "click", "kind": "implicit", "weight": 0.3,
        }
        assert _count(db_session, uid) == 1

    def test_explicit_thumbs_up_recorded(self, db_session):
        uid = _uid()
        out = record_feedback(db_session, user_id=uid, query="ai crm", result_ref="r1", signal="thumbs_up")
        assert out["kind"] == "explicit"
        assert out["weight"] == 1.0

    def test_dedup_repeated_signal_counts_once(self, db_session):
        uid = _uid()
        record_feedback(db_session, user_id=uid, query="q", result_ref="r1", signal="click")
        second = record_feedback(db_session, user_id=uid, query="q", result_ref="r1", signal="click")
        assert second["created"] is False
        assert _count(db_session, uid) == 1

    def test_distinct_signals_coexist(self, db_session):
        uid = _uid()
        record_feedback(db_session, user_id=uid, query="q", result_ref="r1", signal="click")
        record_feedback(db_session, user_id=uid, query="q", result_ref="r1", signal="convert")
        assert _count(db_session, uid) == 2

    def test_explicit_flip_clears_opposing_vote(self, db_session):
        uid = _uid()
        record_feedback(db_session, user_id=uid, query="q", result_ref="r1", signal="thumbs_up")
        record_feedback(db_session, user_id=uid, query="q", result_ref="r1", signal="thumbs_down")
        rows = (
            db_session.query(SearchResultFeedback)
            .filter(SearchResultFeedback.user_id == uuid.UUID(uid))
            .all()
        )
        assert len(rows) == 1
        assert rows[0].signal == "thumbs_down"

    def test_query_is_normalized(self, db_session):
        uid = _uid()
        record_feedback(db_session, user_id=uid, query="  ai crm  ", result_ref="r1", signal="click")
        record_feedback(db_session, user_id=uid, query="ai crm", result_ref="r1", signal="click")
        assert _count(db_session, uid) == 1  # same normalized query -> dedup

    def test_unknown_signal_raises(self, db_session):
        with pytest.raises(ValueError):
            record_feedback(db_session, user_id=_uid(), query="q", result_ref="r1", signal="nope")

    def test_missing_result_ref_raises(self, db_session):
        with pytest.raises(ValueError):
            record_feedback(db_session, user_id=_uid(), query="q", result_ref="", signal="click")

    def test_signal_case_insensitive(self, db_session):
        uid = _uid()
        out = record_feedback(db_session, user_id=uid, query="q", result_ref="r1", signal="Thumbs_Up")
        assert out["signal"] == "thumbs_up"


class TestOutcomeWeights:

    def test_empty_when_no_feedback(self, db_session):
        assert get_result_outcome_weights(db_session, _uid(), "q") == {}

    def test_blends_implicit_and_explicit(self, db_session):
        uid = _uid()
        record_feedback(db_session, user_id=uid, query="q", result_ref="r1", signal="click")      # +0.3
        record_feedback(db_session, user_id=uid, query="q", result_ref="r1", signal="thumbs_up")   # +1.0
        record_feedback(db_session, user_id=uid, query="q", result_ref="r2", signal="thumbs_down") # -1.0
        weights = get_result_outcome_weights(db_session, uid, "q")
        assert weights["r1"] == pytest.approx(1.3)
        assert weights["r2"] == pytest.approx(-1.0)

    def test_scoped_per_query(self, db_session):
        uid = _uid()
        record_feedback(db_session, user_id=uid, query="q1", result_ref="r1", signal="convert")
        record_feedback(db_session, user_id=uid, query="q2", result_ref="r1", signal="dismiss")
        assert get_result_outcome_weights(db_session, uid, "q1") == {"r1": 1.0}
        assert get_result_outcome_weights(db_session, uid, "q2") == {"r1": -0.3}

    def test_scoped_per_user(self, db_session):
        u1, u2 = _uid(), _uid()
        record_feedback(db_session, user_id=u1, query="q", result_ref="r1", signal="convert")
        assert get_result_outcome_weights(db_session, u2, "q") == {}

    def test_all_signal_weights_addressable(self, db_session):
        uid = _uid()
        for i, signal in enumerate(SIGNAL_WEIGHTS):
            record_feedback(db_session, user_id=uid, query="q", result_ref=f"r{i}", signal=signal)
        weights = get_result_outcome_weights(db_session, uid, "q")
        assert len(weights) == len(SIGNAL_WEIGHTS)


class TestRankingConsumption:
    """The §8 payoff: captured feedback re-weights the unified search ranking,
    but only behind the flag (default off = ranking byte-for-byte unchanged)."""

    def test_outcome_weights_for_is_none_when_flag_off(self, db_session, monkeypatch):
        from apps.search.syscalls import _outcome_weights_for

        monkeypatch.delenv("AINDY_SEARCH_OUTCOME_WEIGHTING", raising=False)
        uid = _uid()
        record_feedback(db_session, user_id=uid, query="q", result_ref="r1", signal="thumbs_up")
        assert _outcome_weights_for(db_session, uid, "q") is None

    def test_outcome_weights_for_returns_weights_when_flag_on(self, db_session, monkeypatch):
        from apps.search.syscalls import _outcome_weights_for

        monkeypatch.setenv("AINDY_SEARCH_OUTCOME_WEIGHTING", "1")
        uid = _uid()
        record_feedback(db_session, user_id=uid, query="q", result_ref="r1", signal="convert")
        assert _outcome_weights_for(db_session, uid, "q") == {"r1": 1.0}

    def test_outcome_weights_for_none_without_user(self, db_session, monkeypatch):
        from apps.search.syscalls import _outcome_weights_for

        monkeypatch.setenv("AINDY_SEARCH_OUTCOME_WEIGHTING", "1")
        assert _outcome_weights_for(db_session, None, "q") is None

    def test_search_syscall_reorders_by_feedback_when_enabled(self, db_session, monkeypatch):
        from AINDY.kernel.syscall_registry import SyscallContext
        from apps.search import syscalls
        from apps.search.services import search_service

        uid = _uid()
        query = "cloud security"

        # Two equally-scored, equally-relevant leads — order decided by feedback.
        def _fake_search_leads(q, db=None, user_id=None, max_results=3):
            return {
                "query": q,
                "results": [
                    {"company": "Alpha", "url": "https://alpha.io",
                     "context": "cloud security", "overall_score": 50},
                    {"company": "Beta", "url": "https://beta.io",
                     "context": "cloud security", "overall_score": 50},
                ],
            }

        monkeypatch.setattr(search_service, "search_leads", _fake_search_leads)
        monkeypatch.setenv("AINDY_SEARCH_OUTCOME_WEIGHTING", "1")

        # The user converted on Beta and dismissed Alpha.
        record_feedback(db_session, user_id=uid, query=query, result_ref="https://beta.io", signal="convert")
        record_feedback(db_session, user_id=uid, query=query, result_ref="https://alpha.io", signal="dismiss")

        ctx = SyscallContext(
            execution_unit_id="eu-test", user_id=uid, capabilities=[],
            trace_id="tr-test", metadata={"_db": db_session},
        )
        out = syscalls._handle_search_query(
            {"query": query, "search_type": "leadgen"}, ctx
        )
        assert out["results"][0]["url"] == "https://beta.io"
        assert out["results"][0]["metadata"]["outcome_weight"] == 1.0

    def test_search_syscall_default_order_when_flag_off(self, db_session, monkeypatch):
        from AINDY.kernel.syscall_registry import SyscallContext
        from apps.search import syscalls
        from apps.search.services import search_service

        uid = _uid()
        query = "cloud security"

        def _fake_search_leads(q, db=None, user_id=None, max_results=3):
            return {
                "query": q,
                "results": [
                    {"company": "Alpha", "url": "https://alpha.io",
                     "context": "cloud security", "overall_score": 50},
                    {"company": "Beta", "url": "https://beta.io",
                     "context": "cloud security", "overall_score": 50},
                ],
            }

        monkeypatch.setattr(search_service, "search_leads", _fake_search_leads)
        monkeypatch.delenv("AINDY_SEARCH_OUTCOME_WEIGHTING", raising=False)
        record_feedback(db_session, user_id=uid, query=query, result_ref="https://beta.io", signal="convert")

        ctx = SyscallContext(
            execution_unit_id="eu-test", user_id=uid, capabilities=[],
            trace_id="tr-test", metadata={"_db": db_session},
        )
        out = syscalls._handle_search_query({"query": query, "search_type": "leadgen"}, ctx)
        # Flag off -> feedback ignored -> stable original order, no annotation.
        assert out["results"][0]["url"] == "https://alpha.io"
        assert "outcome_weight" not in out["results"][0]["metadata"]
