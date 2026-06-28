"""Comment / reply persistence for the social layer.

This is the content surface behind the flattened ``SocialPost.comments_count``
counter. Comments live in the Mongo ``comments`` collection; replies carry a
``parent_comment_id`` so threads can be reconstructed.

Kept free of FastAPI/auth concerns so it can be unit-tested directly against a
Mongo (or Mongo-compatible) database handle. The router resolves identity and
maps :class:`CommentValidationError` onto HTTP responses.
"""

from __future__ import annotations

from typing import Any

from apps.social.models.social_models import SocialComment


class CommentValidationError(Exception):
    """Raised for caller-fixable problems (missing post, bad parent, empty body).

    ``status_code``/``error`` let the router translate the failure into a
    structured HTTP error without string-matching the message.
    """

    def __init__(self, *, status_code: int, error: str, message: str) -> None:
        self.status_code = status_code
        self.error = error
        self.message = message
        super().__init__(message)


def _strip_mongo_id(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("_id", None)
    return doc


def create_comment(
    db: Any,
    *,
    post_id: str,
    author_id: str,
    author_username: str,
    content: str,
    parent_comment_id: str | None = None,
) -> dict[str, Any]:
    """Persist a comment (or reply) and bump the post's ``comments_count``.

    Raises :class:`CommentValidationError` if the content is empty, the post does
    not exist, or ``parent_comment_id`` does not resolve to a comment on the same
    post.
    """
    text = (content or "").strip()
    if not text:
        raise CommentValidationError(
            status_code=422,
            error="invalid_comment",
            message="Comment content is required",
        )

    if db["posts"].find_one({"id": post_id}) is None:
        raise CommentValidationError(
            status_code=404,
            error="post_not_found",
            message="Post not found",
        )

    if parent_comment_id:
        parent = db["comments"].find_one({"id": parent_comment_id})
        if parent is None:
            raise CommentValidationError(
                status_code=404,
                error="parent_comment_not_found",
                message="Parent comment not found",
            )
        if parent.get("post_id") != post_id:
            raise CommentValidationError(
                status_code=422,
                error="parent_comment_mismatch",
                message="Parent comment belongs to a different post",
            )

    comment = SocialComment(
        post_id=post_id,
        author_id=author_id,
        author_username=author_username,
        content=text,
        parent_comment_id=parent_comment_id,
    )
    doc = comment.dict()
    # Insert a copy so the returned doc is not mutated with Mongo's _id.
    db["comments"].insert_one(dict(doc))
    db["posts"].update_one({"id": post_id}, {"$inc": {"comments_count": 1}})
    return doc


def list_comments(
    db: Any,
    *,
    post_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return a post's comments in chronological order (oldest first).

    The list is flat; each reply carries ``parent_comment_id`` so the caller can
    reconstruct threads. ``limit`` is clamped to a sane upper bound.
    """
    safe_limit = max(1, min(int(limit or 100), 500))
    cursor = (
        db["comments"]
        .find({"post_id": post_id})
        .sort("created_at", 1)
        .limit(safe_limit)
    )
    return [_strip_mongo_id(dict(doc)) for doc in cursor]
