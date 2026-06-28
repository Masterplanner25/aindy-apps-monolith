"""Unit tests for bridge-event surfacing in the social feed.

Covers the origin-gated normalization service and the feed response adapter that
exposes the `events` channel alongside `data` (posts).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.app_profile

bridge_feed = pytest.importorskip("apps.social.services.bridge_feed_service")
social_router = pytest.importorskip("apps.social.routes.social_router")
get_bridge_feed_events = bridge_feed.get_bridge_feed_events
surfaceable_origins = bridge_feed.surfaceable_origins
social_feed_response_adapter = social_router.social_feed_response_adapter


# --- surfaceable_origins -----------------------------------------------------
def test_surfaceable_origins_default(monkeypatch):
    monkeypatch.delenv("SOCIAL_FEED_BRIDGE_ORIGINS", raising=False)
    assert surfaceable_origins() == {"system"}


def test_surfaceable_origins_parses_and_trims(monkeypatch):
    monkeypatch.setenv("SOCIAL_FEED_BRIDGE_ORIGINS", " system , public ,,")
    assert surfaceable_origins() == {"system", "public"}


def test_surfaceable_origins_blank_is_empty(monkeypatch):
    monkeypatch.setenv("SOCIAL_FEED_BRIDGE_ORIGINS", "   ")
    assert surfaceable_origins() == set()


# --- get_bridge_feed_events --------------------------------------------------
def test_get_bridge_feed_events_normalizes_and_omits_user_name(monkeypatch):
    monkeypatch.setenv("SOCIAL_FEED_BRIDGE_ORIGINS", "system")
    captured = {}

    def fake_list(db, *, origins=None, limit=50):
        captured["origins"] = origins
        captured["limit"] = limit
        return [
            {"user_name": "alice", "origin": "system", "occurred_at": "2026-01-01T00:00:00Z", "created_at": "x"},
            {"user_name": "bob", "origin": "system", "occurred_at": None, "created_at": "2026-01-02T00:00:00Z"},
        ]

    monkeypatch.setattr("apps.automation.public.list_bridge_user_events", fake_list)

    events = get_bridge_feed_events(object(), limit=20)

    assert captured["origins"] == ["system"]  # sorted list of the allowlist
    assert captured["limit"] == 20
    assert events[0] == {
        "kind": "bridge_event",
        "origin": "system",
        "occurred_at": "2026-01-01T00:00:00Z",
        "summary": "Activity via system",
    }
    # occurred_at falls back to created_at; user_name never surfaces
    assert events[1]["occurred_at"] == "2026-01-02T00:00:00Z"
    assert all("user_name" not in e for e in events)


def test_get_bridge_feed_events_empty_allowlist_skips_query(monkeypatch):
    monkeypatch.setenv("SOCIAL_FEED_BRIDGE_ORIGINS", "")

    def boom(*a, **k):
        raise AssertionError("automation should not be queried when allowlist is empty")

    monkeypatch.setattr("apps.automation.public.list_bridge_user_events", boom)
    assert get_bridge_feed_events(object()) == []


def test_get_bridge_feed_events_swallows_errors(monkeypatch):
    monkeypatch.setenv("SOCIAL_FEED_BRIDGE_ORIGINS", "system")

    def boom(*a, **k):
        raise RuntimeError("automation unavailable")

    monkeypatch.setattr("apps.automation.public.list_bridge_user_events", boom)
    assert get_bridge_feed_events(object()) == []


# --- social_feed_response_adapter -------------------------------------------
def _body(resp):
    return json.loads(bytes(resp.body))


def test_feed_adapter_splits_posts_and_events():
    canonical = {
        "status": "SUCCESS",
        "data": {"posts": [{"post": {"id": "p1"}}], "events": [{"kind": "bridge_event", "origin": "system"}]},
        "trace_id": "trace-1",
        "metadata": {},
    }
    resp = social_feed_response_adapter(
        route_name="social.feed.get", canonical=canonical, status_code=200, trace_headers={}
    )
    body = _body(resp)
    assert resp.status_code == 200
    assert body["status"] == "SUCCESS"
    assert body["data"] == [{"post": {"id": "p1"}}]  # backward-compatible: data is the post list
    assert body["result"] == body["data"]
    assert body["events"] == [{"kind": "bridge_event", "origin": "system"}]
    assert body["trace_id"] == "trace-1"


def test_feed_adapter_error_path():
    canonical = {
        "status": "error",
        "metadata": {"status_code": 404, "error": {"detail": "boom"}},
    }
    resp = social_feed_response_adapter(
        route_name="social.feed.get", canonical=canonical, status_code=200, trace_headers={}
    )
    assert resp.status_code == 404
    assert _body(resp) == {"detail": {"detail": "boom"}}


def test_feed_adapter_degraded_list_fallback():
    # Degraded feed returns data=[] (a list, not the posts/events dict).
    canonical = {"status": "SUCCESS", "data": [], "trace_id": "", "metadata": {}}
    resp = social_feed_response_adapter(
        route_name="social.feed.get", canonical=canonical, status_code=200, trace_headers={}
    )
    body = _body(resp)
    assert body["data"] == []
    assert body["events"] == []


# --- end-to-end: real automation SQL query through the service ---------------
def _build_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from AINDY.db.database import Base
    from tests.helpers.app_profile import bootstrap_app_models
    from tests.helpers.runtime import import_runtime_model_registry

    import_runtime_model_registry()
    bootstrap_app_models(required=True)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)()


def test_end_to_end_filters_by_origin_and_orders_recent_first(monkeypatch):
    from apps.automation.models import BridgeUserEvent

    monkeypatch.setenv("SOCIAL_FEED_BRIDGE_ORIGINS", "system")
    session = _build_session()
    try:
        session.add_all(
            [
                BridgeUserEvent(
                    user_name="alice", origin="system", raw_timestamp=None,
                    occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                ),
                BridgeUserEvent(
                    user_name="bob", origin="system", raw_timestamp=None,
                    occurred_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
                ),
                BridgeUserEvent(
                    user_name="carol", origin="chrome_extension", raw_timestamp=None,
                    occurred_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                ),
            ]
        )
        session.commit()

        events = get_bridge_feed_events(session, limit=10)

        # Only system-origin events, most recent first; non-system excluded.
        assert [e["origin"] for e in events] == ["system", "system"]
        assert events[0]["occurred_at"] > events[1]["occurred_at"]
        assert all(e["kind"] == "bridge_event" for e in events)
    finally:
        session.close()
