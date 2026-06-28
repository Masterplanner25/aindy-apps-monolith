"""Unit tests for binding the social profile identity to the canonical user.

Covers `resolve_canonical_username` against the runtime `users` table and the
comment-author precedence (canonical username wins over client-supplied / social
profile / slug).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.app_profile

binding = pytest.importorskip("apps.social.services.identity_binding_service")
social_router = pytest.importorskip("apps.social.routes.social_router")
resolve_canonical_username = binding.resolve_canonical_username
_resolve_comment_author = social_router._resolve_comment_author


def _build_sql_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from AINDY.db.database import Base
    from AINDY.db.models.user import User  # noqa: F401 — registers the table
    from tests.helpers.app_profile import bootstrap_app_models
    from tests.helpers.runtime import import_runtime_model_registry

    import_runtime_model_registry()
    bootstrap_app_models(required=True)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)()


def _add_user(session, *, username):
    from AINDY.db.models.user import User

    uid = uuid.uuid4()
    session.add(
        User(id=uid, email=f"{uid}@example.com", username=username, hashed_password="x", is_active=True)
    )
    session.commit()
    return str(uid)


# --- in-memory Mongo profiles fake (for _resolve_comment_author) -------------
class _FakeProfiles:
    def __init__(self, docs):
        self._docs = docs

    def find_one(self, query):
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None


class _FakeMongo:
    def __init__(self, profiles=None):
        self._profiles = _FakeProfiles(profiles or [])

    def __getitem__(self, name):
        assert name == "profiles"
        return self._profiles


# --- resolve_canonical_username ---------------------------------------------
def test_canonical_username_present():
    session = _build_sql_session()
    try:
        user_id = _add_user(session, username="alice")
        assert resolve_canonical_username(session, user_id) == ("alice", True)
    finally:
        session.close()


def test_canonical_username_null_is_unverified():
    session = _build_sql_session()
    try:
        user_id = _add_user(session, username=None)
        assert resolve_canonical_username(session, user_id) == (None, False)
    finally:
        session.close()


def test_canonical_username_missing_user():
    session = _build_sql_session()
    try:
        assert resolve_canonical_username(session, str(uuid.uuid4())) == (None, False)
    finally:
        session.close()


def test_canonical_username_invalid_id():
    session = _build_sql_session()
    try:
        assert resolve_canonical_username(session, "not-a-uuid") == (None, False)
    finally:
        session.close()


# --- _resolve_comment_author precedence -------------------------------------
def test_comment_author_prefers_canonical_over_everything():
    session = _build_sql_session()
    try:
        user_id = _add_user(session, username="canon")
        mongo = _FakeMongo([{"user_id": user_id, "username": "social_name"}])
        # canonical wins even when a client value and a social profile exist
        assert _resolve_comment_author(mongo, session, user_id, "client_supplied") == "canon"
    finally:
        session.close()


def test_comment_author_falls_back_when_no_canonical():
    session = _build_sql_session()
    try:
        user_id = _add_user(session, username=None)
        mongo = _FakeMongo([{"user_id": user_id, "username": "social_name"}])
        # no canonical -> client-supplied wins next
        assert _resolve_comment_author(mongo, session, user_id, "client_supplied") == "client_supplied"
        # then social profile username
        assert _resolve_comment_author(mongo, session, user_id, None) == "social_name"
    finally:
        session.close()


def test_comment_author_slug_when_nothing_available():
    session = _build_sql_session()
    try:
        user_id = _add_user(session, username=None)
        mongo = _FakeMongo([])  # no profile
        result = _resolve_comment_author(mongo, session, user_id, None)
        assert result == f"user-{user_id[:8]}"
    finally:
        session.close()
