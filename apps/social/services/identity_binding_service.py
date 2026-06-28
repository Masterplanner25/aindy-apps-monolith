"""Bind the social profile's identity to the canonical user.

The canonical username lives on the runtime-owned ``users`` table
(``users.username``, unique but nullable). The Mongo ``SocialProfile`` and the
denormalized post ``author_username`` are otherwise set independently and can
drift. This helper reads the canonical username so write paths can source it.

Per the agreed scope (username-binding only): when the canonical username is
present it is authoritative; when it is NULL the social layer may keep its own
username flagged unverified — it NEVER writes the runtime ``users`` table.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id


def resolve_canonical_username(db: Session, user_id: str) -> tuple[str | None, bool]:
    """Return ``(username, is_canonical)`` for a user.

    ``is_canonical`` is True only when the runtime ``users`` row exists and has a
    non-empty ``username``. Best-effort: any failure resolves to ``(None, False)``
    so callers fall back to the social-only (unverified) path.
    """
    user_uuid = parse_user_id(user_id)
    if user_uuid is None:
        return None, False

    try:
        from AINDY.db.models.user import User

        user = db.query(User).filter(User.id == user_uuid).first()
    except Exception:
        return None, False

    if user is None:
        return None, False

    username = getattr(user, "username", None)
    if username and str(username).strip():
        return str(username).strip(), True
    return None, False
