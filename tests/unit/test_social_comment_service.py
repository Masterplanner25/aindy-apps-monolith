"""Unit tests for the social comment/reply service.

Exercises ``apps.social.services.comment_service`` directly against a minimal
in-memory Mongo fake (mongomock is not a dependency), covering validation,
counter increment, and thread (reply) integrity.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.app_profile

comment_service = pytest.importorskip("apps.social.services.comment_service")
create_comment = comment_service.create_comment
list_comments = comment_service.list_comments
CommentValidationError = comment_service.CommentValidationError


# --- minimal in-memory Mongo fake -------------------------------------------
class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, field, direction=1):
        self._docs.sort(key=lambda d: d.get(field), reverse=(direction == -1))
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeCollection:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _match(doc, query):
        for key, val in query.items():
            if isinstance(val, dict) and "$in" in val:
                if doc.get(key) not in val["$in"]:
                    return False
            elif doc.get(key) != val:
                return False
        return True

    def insert_one(self, doc):
        stored = dict(doc)
        stored.setdefault("_id", f"oid-{len(self.docs)}")
        self.docs.append(stored)

    def find(self, query=None):
        query = query or {}
        return _FakeCursor([dict(d) for d in self.docs if self._match(d, query)])

    def find_one(self, query):
        for doc in self.docs:
            if self._match(doc, query):
                return dict(doc)
        return None

    def update_one(self, query, update):
        for doc in self.docs:
            if self._match(doc, query):
                for key, amount in update.get("$inc", {}).items():
                    doc[key] = (doc.get(key, 0) or 0) + amount
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
                return


class _FakeDB:
    def __init__(self):
        self._collections = {}

    def __getitem__(self, name):
        return self._collections.setdefault(name, _FakeCollection())


def _db_with_post(post_id="post-1", comments_count=0):
    db = _FakeDB()
    db["posts"].insert_one({"id": post_id, "comments_count": comments_count, "impressions": 0})
    return db


# --- create_comment ----------------------------------------------------------
def test_create_comment_persists_and_increments_counter():
    db = _db_with_post(comments_count=2)

    comment = create_comment(
        db,
        post_id="post-1",
        author_id="user-abc",
        author_username="alice",
        content="  great post  ",
    )

    assert comment["post_id"] == "post-1"
    assert comment["author_username"] == "alice"
    assert comment["content"] == "great post"  # trimmed
    assert comment["parent_comment_id"] is None
    assert "_id" not in comment  # returned doc stays clean

    stored = db["comments"].find_one({"id": comment["id"]})
    assert stored is not None
    assert db["posts"].find_one({"id": "post-1"})["comments_count"] == 3


def test_create_comment_rejects_empty_content():
    db = _db_with_post()
    with pytest.raises(CommentValidationError) as exc:
        create_comment(db, post_id="post-1", author_id="u", author_username="a", content="   ")
    assert exc.value.status_code == 422
    assert exc.value.error == "invalid_comment"
    # counter untouched
    assert db["posts"].find_one({"id": "post-1"})["comments_count"] == 0


def test_create_comment_rejects_missing_post():
    db = _FakeDB()  # no posts at all
    with pytest.raises(CommentValidationError) as exc:
        create_comment(db, post_id="ghost", author_id="u", author_username="a", content="hi")
    assert exc.value.status_code == 404
    assert exc.value.error == "post_not_found"


def test_reply_to_valid_parent_succeeds():
    db = _db_with_post()
    parent = create_comment(db, post_id="post-1", author_id="u1", author_username="a", content="root")

    reply = create_comment(
        db,
        post_id="post-1",
        author_id="u2",
        author_username="b",
        content="reply",
        parent_comment_id=parent["id"],
    )

    assert reply["parent_comment_id"] == parent["id"]
    assert db["posts"].find_one({"id": "post-1"})["comments_count"] == 2


def test_reply_to_missing_parent_rejected():
    db = _db_with_post()
    with pytest.raises(CommentValidationError) as exc:
        create_comment(
            db,
            post_id="post-1",
            author_id="u",
            author_username="a",
            content="reply",
            parent_comment_id="nope",
        )
    assert exc.value.status_code == 404
    assert exc.value.error == "parent_comment_not_found"


def test_reply_to_parent_on_other_post_rejected():
    db = _db_with_post(post_id="post-1")
    db["posts"].insert_one({"id": "post-2", "comments_count": 0})
    other_parent = create_comment(db, post_id="post-2", author_id="u", author_username="a", content="elsewhere")

    with pytest.raises(CommentValidationError) as exc:
        create_comment(
            db,
            post_id="post-1",
            author_id="u",
            author_username="a",
            content="reply",
            parent_comment_id=other_parent["id"],
        )
    assert exc.value.status_code == 422
    assert exc.value.error == "parent_comment_mismatch"


# --- list_comments -----------------------------------------------------------
def test_list_comments_is_chronological_and_clean():
    db = _db_with_post()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Insert out of order to prove the service sorts by created_at ascending.
    for idx in (2, 0, 1):
        db["comments"].insert_one(
            {
                "id": f"c{idx}",
                "post_id": "post-1",
                "author_id": "u",
                "author_username": "a",
                "content": f"comment {idx}",
                "parent_comment_id": None,
                "created_at": base + timedelta(minutes=idx),
            }
        )

    result = list_comments(db, post_id="post-1")

    assert [c["id"] for c in result] == ["c0", "c1", "c2"]
    assert all("_id" not in c for c in result)


def test_list_comments_scopes_to_post_and_clamps_limit():
    db = _db_with_post(post_id="post-1")
    db["posts"].insert_one({"id": "post-2", "comments_count": 0})
    create_comment(db, post_id="post-1", author_id="u", author_username="a", content="keep")
    create_comment(db, post_id="post-2", author_id="u", author_username="a", content="other")

    result = list_comments(db, post_id="post-1", limit=0)  # clamped up to >=1

    assert len(result) == 1
    assert result[0]["content"] == "keep"
