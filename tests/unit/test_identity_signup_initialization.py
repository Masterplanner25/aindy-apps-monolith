"""Signup initialization must run from the auth.register.completed event.

Regression: the handler read ``event.get("db")`` and returned early on EVERY signup, because
``dispatch_internal_event_handlers`` builds the handler event as
``{event_id, event_type, payload, user_id, trace_id, source}`` — there is deliberately no
``db`` key. Signup init therefore never ran: no UserIdentity, no user_scores, no initial
memory node, no initial agent run, on any account ever created. It failed silently (handler
returned None, dispatch counted it "ok"), which is why it went unnoticed.

These tests pin the REAL event contract, so a handler that depends on a key the runtime does
not send fails here instead of in production.
"""
from __future__ import annotations

import uuid

import pytest

from apps.identity import bootstrap as identity_bootstrap

pytestmark = pytest.mark.app_profile


def _runtime_event(user_id, event_type="auth.register.completed") -> dict:
    """Exactly the dict shape AINDY.platform_layer.event_service hands to handlers.

    Deliberately has no "db" key — mirroring dispatch_internal_event_handlers.
    """
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "payload": {"email": "someone@example.com", "username": "someone"},
        "user_id": str(user_id) if user_id is not None else None,
        "trace_id": None,
        "source": "auth",
    }


def test_runtime_event_contract_has_no_db_key():
    """Guards the assumption this whole fix rests on."""
    event = _runtime_event(uuid.uuid4())
    assert "db" not in event
    assert set(event) == {"event_id", "event_type", "payload", "user_id", "trace_id", "source"}


def test_handler_initializes_signup_state_from_runtime_event(monkeypatch):
    """The handler must open its own session and call initialize_signup_state."""
    uid = uuid.uuid4()
    calls = {}

    class _FakeUser:
        id = uid
        email = "someone@example.com"
        created_at = None

    class _FakeQuery:
        def filter(self, *a, **k):
            return self

        def first(self):
            return _FakeUser()

    class _FakeSession:
        def __init__(self):
            calls["session_opened"] = calls.get("session_opened", 0) + 1

        def query(self, *a, **k):
            return _FakeQuery()

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr("AINDY.db.database.SessionLocal", _FakeSession)
    monkeypatch.setattr(
        "apps.identity.services.signup_initialization_service.initialize_signup_state",
        lambda *, db, user: calls.update({"initialized": user.id}) or {},
    )

    identity_bootstrap._handle_auth_register_completed(_runtime_event(uid))

    assert calls.get("session_opened") == 1, "handler must open its own session"
    assert calls.get("initialized") == uid, "signup init must run for the registered user"
    assert calls.get("closed") is True, "session must be closed"


def test_handler_skips_cleanly_without_user_id(monkeypatch):
    opened = []
    monkeypatch.setattr("AINDY.db.database.SessionLocal",
                        lambda: opened.append(1) or (_ for _ in ()).throw(AssertionError))
    identity_bootstrap._handle_auth_register_completed(_runtime_event(None))
    assert opened == [], "no session should be opened when the event carries no user_id"


def test_handler_raises_so_failures_are_not_silent(monkeypatch):
    """The original bug hid because nothing surfaced. A failing init must propagate."""
    uid = uuid.uuid4()

    class _FakeUser:
        id = uid

    class _FakeQuery:
        def filter(self, *a, **k):
            return self

        def first(self):
            return _FakeUser()

    class _FakeSession:
        def query(self, *a, **k):
            return _FakeQuery()

        def close(self):
            pass

    def _boom(*, db, user):
        raise RuntimeError("init exploded")

    monkeypatch.setattr("AINDY.db.database.SessionLocal", _FakeSession)
    monkeypatch.setattr(
        "apps.identity.services.signup_initialization_service.initialize_signup_state", _boom
    )

    with pytest.raises(RuntimeError, match="init exploded"):
        identity_bootstrap._handle_auth_register_completed(_runtime_event(uid))
