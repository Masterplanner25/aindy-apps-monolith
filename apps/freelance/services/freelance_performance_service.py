"""Freelance performance signals — the Revenue tether into Infinity.

Mirrors apps/social/services/social_performance_service.py: returns a short list of recent
realized-revenue signals (``{type, reason, ...}``) that the analytics ``dependency_adapter``
fetches via ``sys.v1.freelance.get_performance_signals`` and threads into the Infinity support
state. This restores the "reports into Infinity" tether the architecture review found lost for
Freelance's revenue loop. Observability only — it does not change the canonical KPI math.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from apps.freelance.models.freelance import FreelanceOrder


def get_freelance_performance_signals(
    db: Session, *, user_id: str | None = None, limit: int = 3
) -> list[dict[str, Any]]:
    """Recent realized-revenue signals for a user (safe/degradable — returns [] on any issue)."""
    if not user_id:
        return []
    try:
        rows = (
            db.query(FreelanceOrder)
            .filter(FreelanceOrder.user_id == user_id)
            .order_by(FreelanceOrder.created_at.desc())
            .limit(100)
            .all()
        )
    except Exception:
        return []
    if not rows:
        return []

    signals: list[dict[str, Any]] = []
    paid = [r for r in rows if r.payment_confirmed_at is not None]
    if paid:
        realized = sum(float(r.price or 0.0) for r in paid)
        signals.append(
            {
                "type": "success",
                "reason": "realized_revenue",
                "order_count": len(paid),
                "realized_revenue": round(realized, 2),
            }
        )
    return signals[:limit]
