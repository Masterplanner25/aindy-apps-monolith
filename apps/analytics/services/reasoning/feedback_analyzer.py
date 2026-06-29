"""Feedback analyzer — normalize recent feedback into a reasoning input.

Phase 2 of the Autonomous Reasoning evolution. Turns recent feedback rows (ORM
rows or dicts) into the standardized feedback context the decision engine reads,
so feedback becomes a first-class, reusable reasoning input rather than logic
embedded in the loop. Pure — the caller fetches the rows.
"""

from __future__ import annotations

from typing import Any


def _get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def summarize_feedback(rows: list[Any] | None) -> dict[str, Any]:
    """Summarize feedback rows into ``{count, positive, negative, latest_feedback_text}``.

    Rows may be ORM objects or dicts with ``feedback_value`` (int; sign = polarity)
    and ``feedback_text``.
    """
    rows = rows or []
    if not rows:
        return {"count": 0, "positive": 0, "negative": 0, "latest_feedback_text": None}
    positives = sum(1 for row in rows if int(_get(row, "feedback_value") or 0) > 0)
    negatives = sum(1 for row in rows if int(_get(row, "feedback_value") or 0) < 0)
    return {
        "count": len(rows),
        "positive": positives,
        "negative": negatives,
        "latest_feedback_text": next(
            (_get(row, "feedback_text") for row in rows if _get(row, "feedback_text")),
            None,
        ),
    }
