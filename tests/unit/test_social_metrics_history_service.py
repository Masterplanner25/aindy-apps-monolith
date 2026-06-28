"""Unit tests for durable social metrics history.

Exercises ``apps.social.services.social_metrics_history_service`` against a
minimal in-memory Mongo fake supporting upsert / $inc / $setOnInsert (mongomock
is not a dependency). Covers per-day delta accumulation and trend rebuilding,
including per-user scoping and the day-window clamp.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.app_profile

history_service = pytest.importorskip("apps.social.services.social_metrics_history_service")
record_metric_deltas = history_service.record_metric_deltas
build_trend_from_history = history_service.build_trend_from_history
HISTORY_COLLECTION = history_service.HISTORY_COLLECTION


# --- in-memory Mongo fake with upsert support --------------------------------
class _FakeCollection:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _match(doc, query):
        return all(doc.get(key) == val for key, val in query.items())

    def find(self, query=None):
        query = query or {}
        return [dict(d) for d in self.docs if self._match(d, query)]

    def find_one(self, query):
        for doc in self.docs:
            if self._match(doc, query):
                return dict(doc)
        return None

    def update_one(self, query, update, upsert=False):
        target = next((d for d in self.docs if self._match(d, query)), None)
        if target is None:
            if not upsert:
                return
            target = {}
            target.update(update.get("$setOnInsert", {}))
            for key, val in query.items():
                target.setdefault(key, val)
            self.docs.append(target)
        for key, amount in update.get("$inc", {}).items():
            target[key] = (target.get(key, 0) or 0) + amount
        for key, val in update.get("$set", {}).items():
            target[key] = val


class _FakeDB:
    def __init__(self):
        self._collections = {}

    def __getitem__(self, name):
        return self._collections.setdefault(name, _FakeCollection())


# --- record_metric_deltas ----------------------------------------------------
def test_record_accumulates_same_day_deltas():
    db = _FakeDB()
    assert record_metric_deltas(post_id="p1", deltas={"impressions": 1}, user_id="owner", day="2026-01-01", db=db)
    record_metric_deltas(post_id="p1", deltas={"impressions": 1, "likes": 1}, user_id="owner", day="2026-01-01", db=db)

    rows = db[HISTORY_COLLECTION].find({"post_id": "p1", "date": "2026-01-01"})
    assert len(rows) == 1  # one doc per (post, day)
    assert rows[0]["impressions"] == 2
    assert rows[0]["likes"] == 1
    assert rows[0]["user_id"] == "owner"


def test_record_separates_distinct_days():
    db = _FakeDB()
    record_metric_deltas(post_id="p1", deltas={"clicks": 3}, day="2026-01-01", db=db)
    record_metric_deltas(post_id="p1", deltas={"clicks": 5}, day="2026-01-02", db=db)

    assert len(db[HISTORY_COLLECTION].find({"post_id": "p1"})) == 2


def test_record_noops_on_zero_or_empty_deltas():
    db = _FakeDB()
    assert record_metric_deltas(post_id="p1", deltas={}, db=db) is False
    assert record_metric_deltas(post_id="p1", deltas={"impressions": 0}, db=db) is False
    assert db[HISTORY_COLLECTION].find({}) == []


def test_record_returns_false_when_db_unavailable():
    # db=None and no Mongo client configured in the test env -> graceful False.
    assert record_metric_deltas(post_id="p1", deltas={"impressions": 1}, db=None) is False


# --- build_trend_from_history ------------------------------------------------
def test_trend_buckets_by_day_with_engagement_score():
    db = _FakeDB()
    # Day 1: 10 impressions, 2 clicks, 1 like across two posts.
    record_metric_deltas(post_id="p1", deltas={"impressions": 6, "clicks": 2, "likes": 1}, user_id="u", day="2026-01-01", db=db)
    record_metric_deltas(post_id="p2", deltas={"impressions": 4}, user_id="u", day="2026-01-01", db=db)
    # Day 2: 5 impressions on p1.
    record_metric_deltas(post_id="p1", deltas={"impressions": 5}, user_id="u", day="2026-01-02", db=db)

    trend = build_trend_from_history(user_id="u", db=db)

    assert [b["date"] for b in trend] == ["2026-01-01", "2026-01-02"]
    day1 = trend[0]
    assert day1["impressions"] == 10
    assert day1["clicks"] == 2
    # weighted = likes(1) + clicks*0.75(1.5) = 2.5; /10 impressions * 100 = 25.0
    assert day1["avg_engagement_score"] == 25.0
    assert trend[1]["impressions"] == 5
    assert trend[1]["avg_engagement_score"] == 0.0


def test_trend_scopes_by_user():
    db = _FakeDB()
    record_metric_deltas(post_id="p1", deltas={"impressions": 3}, user_id="alice", day="2026-01-01", db=db)
    record_metric_deltas(post_id="p2", deltas={"impressions": 9}, user_id="bob", day="2026-01-01", db=db)

    alice = build_trend_from_history(user_id="alice", db=db)
    assert len(alice) == 1 and alice[0]["impressions"] == 3

    everyone = build_trend_from_history(db=db)  # no user filter
    assert everyone[0]["impressions"] == 12


def test_trend_clamps_to_day_window():
    db = _FakeDB()
    for day in range(1, 11):  # 10 distinct days
        record_metric_deltas(post_id="p1", deltas={"impressions": 1}, user_id="u", day=f"2026-01-{day:02d}", db=db)

    trend = build_trend_from_history(user_id="u", days=7, db=db)
    assert len(trend) == 7
    assert trend[0]["date"] == "2026-01-04"  # oldest 3 dropped
    assert trend[-1]["date"] == "2026-01-10"


def test_trend_empty_when_no_history():
    assert build_trend_from_history(user_id="u", db=_FakeDB()) == []
