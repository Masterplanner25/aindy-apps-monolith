"""Reasoning-apply Python vs Nodus-native routing (FR-5 adoption).

The reasoning apply step runs in-process by default; behind AINDY_REASONING_NODUS_NATIVE
it executes the native reasoning_apply_v1.nd on the Nodus VM (reaching app logic via the
sys.v1.analytics.reasoning_recommendation syscall — unblocked by aindy-runtime 1.9.0).

Covers the flag gate, the I/O envelope extraction/normalization, Python-fallback on any
Nodus failure, and one real end-to-end VM run on the app-profile harness.
"""
from __future__ import annotations

import uuid

import pytest

import AINDY.runtime.nodus_workflow_registry as nwr
from apps.analytics.services.reasoning import nodus_apply
from apps.analytics.services.reasoning.nodus_apply import (
    _extract_recommendation,
    nodus_reasoning_enabled,
    run_reasoning_apply,
)

pytestmark = pytest.mark.app_profile


def _nodus_envelope(rec: dict, *, nodus_status="success", syscall_status="success") -> dict:
    return {
        "status": "SUCCESS",
        "data": {
            "nodus_status": nodus_status,
            "nodus_output_state": {
                "reasoning_apply_result": {"status": syscall_status, "data": rec},
            },
        },
    }


class TestFlagAndRouting:

    def test_flag_default_off(self, monkeypatch):
        monkeypatch.delenv("AINDY_REASONING_NODUS_NATIVE", raising=False)
        assert nodus_reasoning_enabled() is False
        monkeypatch.setenv("AINDY_REASONING_NODUS_NATIVE", "1")
        assert nodus_reasoning_enabled() is True

    def test_off_uses_python_path(self, monkeypatch):
        monkeypatch.delenv("AINDY_REASONING_NODUS_NATIVE", raising=False)
        monkeypatch.setattr(
            nodus_apply, "_apply_via_python", lambda db, uid: {"decision_type": "review_plan"}
        )

        def _boom(*a, **k):
            raise AssertionError("nodus path must not run when the flag is off")

        monkeypatch.setattr(nwr, "run_nodus_workflow", _boom)
        out = run_reasoning_apply(db=None, user_id="u1")
        assert out == {"data": {"decision_type": "review_plan"}}

    def test_on_uses_nodus_path_and_normalizes(self, monkeypatch):
        monkeypatch.setenv("AINDY_REASONING_NODUS_NATIVE", "1")
        rec = {"available": True, "decision_type": "continue_highest_priority_task", "reason": "go"}
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda *a, **k: _nodus_envelope(rec))
        out = run_reasoning_apply(db=None, user_id="u1")
        assert out["_via"] == "nodus"
        assert out["data"] == {"decision_type": "continue_highest_priority_task", "reason": "go"}
        assert "available" not in out["data"]  # normalized to the Python-path shape

    def test_on_passes_user_id_to_workflow(self, monkeypatch):
        monkeypatch.setenv("AINDY_REASONING_NODUS_NATIVE", "1")
        captured = {}

        def _capture(name, *, db, user_id, input_payload=None, **k):
            captured.update(name=name, user_id=user_id, input_payload=input_payload)
            return _nodus_envelope({"decision_type": "review_plan"})

        monkeypatch.setattr(nwr, "run_nodus_workflow", _capture)
        run_reasoning_apply(db=None, user_id="user-9")
        assert captured["name"] == "reasoning_apply_v1"
        assert captured["user_id"] == "user-9"
        assert captured["input_payload"] == {"args": {"user_id": "user-9"}}

    def test_falls_back_to_python_on_nodus_exception(self, monkeypatch):
        monkeypatch.setenv("AINDY_REASONING_NODUS_NATIVE", "1")

        def _raise(*a, **k):
            raise RuntimeError("vm boom")

        monkeypatch.setattr(nwr, "run_nodus_workflow", _raise)
        monkeypatch.setattr(nodus_apply, "_apply_via_python", lambda db, uid: {"decision_type": "review_plan"})
        out = run_reasoning_apply(db=None, user_id="u1")
        assert out == {"data": {"decision_type": "review_plan"}}  # no _via -> python

    def test_falls_back_when_vm_did_not_complete(self, monkeypatch):
        monkeypatch.setenv("AINDY_REASONING_NODUS_NATIVE", "1")
        monkeypatch.setattr(
            nwr, "run_nodus_workflow",
            lambda *a, **k: _nodus_envelope({"decision_type": "x"}, nodus_status="failed"),
        )
        monkeypatch.setattr(nodus_apply, "_apply_via_python", lambda db, uid: {"decision_type": "review_plan"})
        out = run_reasoning_apply(db=None, user_id="u1")
        assert out == {"data": {"decision_type": "review_plan"}}


class TestExtraction:

    def test_extract_none_on_failed_nodus(self):
        assert _extract_recommendation(_nodus_envelope({}, nodus_status="failed")) is None

    def test_extract_none_on_failed_syscall(self):
        assert _extract_recommendation(_nodus_envelope({}, syscall_status="error")) is None

    def test_extract_none_on_empty(self):
        assert _extract_recommendation(None) is None
        assert _extract_recommendation({}) is None

    def test_extract_strips_available(self):
        rec = _extract_recommendation(_nodus_envelope({"available": True, "decision_type": "d"}))
        assert rec == {"decision_type": "d"}


class TestSyscallHandler:

    def test_reasoning_syscall_no_snapshot(self, db_session, monkeypatch):
        from AINDY.kernel.syscall_registry import SyscallContext
        from apps.analytics import syscalls as asc

        monkeypatch.setattr(asc, "_session_from_context", lambda ctx: (db_session, False))
        # recommend_next_action returns None when there's no KPI snapshot
        import apps.analytics.services.reasoning as reasoning
        monkeypatch.setattr(reasoning, "recommend_next_action", lambda uid, db: None)
        ctx = SyscallContext(execution_unit_id="eu", user_id=str(uuid.uuid4()),
                             capabilities=[], trace_id="t", metadata={"_db": db_session})
        out = asc._handle_reasoning_recommendation({"user_id": str(uuid.uuid4())}, ctx)
        assert out == {"available": False, "reason": "no_score_snapshot"}

    def test_reasoning_syscall_returns_recommendation(self, db_session, monkeypatch):
        from AINDY.kernel.syscall_registry import SyscallContext
        from apps.analytics import syscalls as asc
        import apps.analytics.services.reasoning as reasoning

        monkeypatch.setattr(asc, "_session_from_context", lambda ctx: (db_session, False))
        monkeypatch.setattr(reasoning, "recommend_next_action",
                            lambda uid, db: {"decision_type": "review_plan", "reason": "ok"})
        ctx = SyscallContext(execution_unit_id="eu", user_id="u1", capabilities=[],
                             trace_id="t", metadata={"_db": db_session})
        out = asc._handle_reasoning_recommendation({"user_id": "u1"}, ctx)
        assert out["available"] is True
        assert out["decision_type"] == "review_plan"


class TestEndToEndNodusVM:
    """Real Nodus VM execution on the app-profile harness — proves the FR-5 path:
    the .nd runs to completion and reaches app reasoning via sys()+app-syscall."""

    def test_real_vm_run_routes_through_nodus(self, db_session, monkeypatch):
        monkeypatch.setenv("AINDY_REASONING_NODUS_NATIVE", "1")
        import AINDY.main  # noqa  (ensure the .nd + syscall are registered)

        # No KPI snapshot for a fresh user -> the syscall returns available:False, the
        # workflow still runs to a successful terminal state (no throw), and the result
        # comes back through the VM (not the Python fallback).
        out = run_reasoning_apply(db_session, str(uuid.uuid4()))
        assert out.get("_via") == "nodus", f"expected nodus path, got: {out}"
        assert out["data"].get("reason") == "no_score_snapshot"
