"""Durable per-day social metrics history.

Background: post engagement counters (`impressions`, `clicks`, `likes`,
`boosts`, `comments_count`) are stored flattened on each post document and
mutated in place. The legacy trend in ``social_performance_service`` bucketed
those *current* totals by the post's ``created_at`` date, so a post's entire
lifetime of activity collapsed into a single creation-day bucket — the trend
did not reflect real per-day movement.

This module records a per-(post, day) snapshot of the *deltas* as interactions
happen, so trends can be rebuilt from durable history. Recording is best-effort:
a history failure must never break the interaction that triggered it.

The history lives in the same ``aindy_social_layer`` database the performance
service reads from, so record and read always agree regardless of how
``MONGO_DB_NAME`` is configured. Functions accept an explicit ``db`` handle for
testing; in production they resolve the social database themselves.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from AINDY.db.mongo_setup import get_mongo_client
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

logger = logging.getLogger(__name__)

SOCIAL_DB_NAME = "aindy_social_layer"
HISTORY_COLLECTION = "social_metrics_history"

# Counter fields tracked in history — the flattened engagement fields on a post.
_METRIC_FIELDS = ("impressions", "clicks", "likes", "boosts", "comments_count")


def _resolve_social_db(db: Any | None) -> Any | None:
    if db is not None:
        return db
    client = get_mongo_client()
    if client is None:
        return None
    return client[SOCIAL_DB_NAME]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def record_metric_deltas(
    *,
    post_id: str,
    deltas: dict[str, int],
    user_id: str | None = None,
    day: str | None = None,
    db: Any | None = None,
) -> bool:
    """Accumulate per-day metric deltas for a post (best-effort, never raises).

    ``user_id`` should be the post **owner** so per-user analytics scope the same
    way the post query does. Returns True if a write was issued, else False
    (Mongo unavailable, nothing to record, or a swallowed error).
    """
    social_db = _resolve_social_db(db)
    if social_db is None:
        return False

    inc = {field: int(amount) for field, amount in deltas.items() if amount}
    if not inc:
        return False

    bucket_day = day or _today()
    try:
        social_db[HISTORY_COLLECTION].update_one(
            {"post_id": post_id, "date": bucket_day},
            {
                "$inc": inc,
                "$setOnInsert": {
                    "post_id": post_id,
                    "date": bucket_day,
                    "user_id": str(user_id) if user_id is not None else None,
                },
            },
            upsert=True,
        )
        return True
    except (ServerSelectionTimeoutError, PyMongoError) as exc:
        logger.warning("social metrics history write failed for post %s: %s", post_id, exc)
        return False


def _bucket_engagement_score(bucket: dict[str, Any]) -> float:
    # Mirror compute_engagement_score, but over the day's deltas.
    impressions = max(1, int(bucket.get("impressions", 0) or 0))
    weighted = (
        int(bucket.get("likes", 0) or 0)
        + int(bucket.get("boosts", 0) or 0) * 2
        + int(bucket.get("comments_count", 0) or 0) * 1.5
        + int(bucket.get("clicks", 0) or 0) * 0.75
    )
    return round((weighted / impressions) * 100.0, 3)


def build_trend_from_history(
    *,
    user_id: str | None = None,
    days: int = 7,
    db: Any | None = None,
) -> list[dict[str, Any]]:
    """Per-day trend buckets from durable history, oldest first (up to ``days``).

    Keeps the legacy ``{date, impressions, clicks, avg_engagement_score}`` shape
    so the analytics contract and frontend are unchanged — but now each bucket is
    real same-day activity rather than lifetime totals on the creation day.
    Returns ``[]`` when there is no history (caller may fall back to legacy).
    """
    social_db = _resolve_social_db(db)
    if social_db is None:
        return []

    query: dict[str, Any] = {}
    if user_id:
        query["user_id"] = str(user_id)

    try:
        docs = list(social_db[HISTORY_COLLECTION].find(query))
    except (ServerSelectionTimeoutError, PyMongoError) as exc:
        logger.warning("social metrics history read failed: %s", exc)
        return []

    buckets: dict[str, dict[str, Any]] = {}
    for doc in docs:
        date = doc.get("date")
        if not date:
            continue
        bucket = buckets.setdefault(
            date,
            {field: 0 for field in _METRIC_FIELDS} | {"date": date},
        )
        for field in _METRIC_FIELDS:
            bucket[field] += int(doc.get(field, 0) or 0)

    ordered = [buckets[key] for key in sorted(buckets)]
    if days and days > 0:
        ordered = ordered[-days:]

    return [
        {
            "date": bucket["date"],
            "impressions": int(bucket["impressions"]),
            "clicks": int(bucket["clicks"]),
            "avg_engagement_score": _bucket_engagement_score(bucket),
        }
        for bucket in ordered
    ]
