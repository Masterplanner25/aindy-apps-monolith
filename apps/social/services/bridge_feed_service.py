"""Surface bridge / system-origin events into the social feed.

Bridge user events (``bridge_user_events``, owned by the automation app) are
thin audit rows — ``user_name``, ``origin``, ``occurred_at`` — with no content.
This service reads them through automation's public contract and normalizes the
ones whose ``origin`` is system/public into a small, honestly-typed shape that
rides alongside posts in the feed response's ``events`` channel.

Scope is deliberately origin-gated rather than per-user: the feed is global and
there is no clean join from a viewer's UUID to the free-string ``user_name``
(that is the social/system identity-unification work). To avoid leaking any
actor identity into the global feed, ``user_name`` is intentionally NOT included
in the surfaced payload.

The set of surfaceable origins is configurable via ``SOCIAL_FEED_BRIDGE_ORIGINS``
(comma-separated), defaulting to ``{"system"}``. An empty/blank setting surfaces
nothing — the safe default.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.orm import Session


def surfaceable_origins() -> set[str]:
    """Origins considered system/public, from env (default ``{"system"}``)."""
    raw = os.getenv("SOCIAL_FEED_BRIDGE_ORIGINS", "system")
    return {token.strip() for token in raw.split(",") if token.strip()}


def _normalize_event(row: dict[str, Any]) -> dict[str, Any]:
    origin = str(row.get("origin") or "")
    occurred_at = row.get("occurred_at") or row.get("created_at")
    return {
        "kind": "bridge_event",
        "origin": origin,
        "occurred_at": occurred_at,
        "summary": f"Activity via {origin}" if origin else "Activity",
    }


def get_bridge_feed_events(db: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent system/public-origin bridge events for the feed channel.

    Best-effort: returns ``[]`` when the origin allowlist is empty or automation
    is unavailable, so it never breaks feed assembly.
    """
    origins = surfaceable_origins()
    if not origins:
        return []

    try:
        from apps.automation.public import list_bridge_user_events

        rows = list_bridge_user_events(db, origins=sorted(origins), limit=limit)
    except Exception:
        return []

    return [_normalize_event(row) for row in rows]
