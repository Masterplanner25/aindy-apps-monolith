"""Search performance signals — the Search (yield) tether into Infinity.

Mirrors apps/social/services/social_performance_service.py: returns a short list of recent
yield signals (``{type, reason, ...}``) that the analytics ``dependency_adapter`` fetches via
``sys.v1.search.get_performance_signals`` and threads into the Infinity support state. This
restores the "reports into Infinity" tether the architecture review found lost for Search's
leadgen yield loop. Observability only — it does not change the canonical KPI math.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from apps.search.models.leadgen_model import LeadGenResult


def get_search_performance_signals(
    db: Session, *, user_id: str | None = None, limit: int = 3
) -> list[dict[str, Any]]:
    """Recent leadgen-yield signals for a user (safe/degradable — returns [] on any issue)."""
    if not user_id:
        return []
    try:
        rows = (
            db.query(LeadGenResult)
            .filter(LeadGenResult.user_id == user_id)
            .order_by(LeadGenResult.created_at.desc())
            .limit(50)
            .all()
        )
    except Exception:
        return []
    if not rows:
        return []

    signals: list[dict[str, Any]] = []
    scored = [r for r in rows if (r.overall_score or 0.0) > 0.0]
    if scored:
        best = max(scored, key=lambda r: r.overall_score or 0.0)
        signals.append(
            {
                "type": "success",
                "reason": "leadgen_yield",
                "lead_count": len(scored),
                "top_score": round(float(best.overall_score or 0.0), 3),
                "company": str(best.company or "")[:80],
            }
        )
    return signals[:limit]
