"""
Public surface for the search domain.
Consumers: freelance
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.search.models import LeadAction, LeadGenResult, ResearchResult, SearchHistory

PUBLIC_API_VERSION = "1.0"


def get_lead_by_id(db, lead_id: Any, user_id: Any = None) -> LeadGenResult | None:
    """Fetch a single leadgen result by id, scoped to ``user_id`` when given.

    Public accessor so the freelance domain can convert a discovered lead into a
    client/order (lead -> client -> order lineage) without reaching into the
    search domain's internals. Returns ``None`` when not found.
    """
    try:
        lead_pk = int(lead_id)
    except (TypeError, ValueError):
        return None
    query = db.query(LeadGenResult).filter(LeadGenResult.id == lead_pk)
    if user_id:
        try:
            query = query.filter(LeadGenResult.user_id == uuid.UUID(str(user_id)))
        except (TypeError, ValueError):
            return None
    return query.first()


def list_actioned_leads(db, user_id: Any, limit: int = 50) -> list[LeadAction]:
    """Pending (non-reverted) lead actions for a user, newest first.

    The Search Execution Layer records a ``LeadAction`` for each qualified lead it
    drafts outreach for. Freelance pulls these to convert an actioned lead into a
    client/order — the decoupled seam that lets search *initiate* the handoff
    without importing freelance (which would create a dependency cycle).
    """
    try:
        uid = uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return []
    return (
        db.query(LeadAction)
        .filter(LeadAction.user_id == uid, LeadAction.status != "reverted")
        .order_by(LeadAction.created_at.desc(), LeadAction.id.desc())
        .limit(limit)
        .all()
    )


def get_lead_action(db, action_id: Any, user_id: Any = None) -> LeadAction | None:
    """Fetch a single lead action by id, scoped to ``user_id`` when given."""
    try:
        action_pk = int(action_id)
    except (TypeError, ValueError):
        return None
    query = db.query(LeadAction).filter(LeadAction.id == action_pk)
    if user_id:
        try:
            query = query.filter(LeadAction.user_id == uuid.UUID(str(user_id)))
        except (TypeError, ValueError):
            return None
    return query.first()


def extract_flow_error(result: dict) -> str:
    from apps.search.services.public_surface_service import extract_flow_error as _extract_flow_error

    return str(_extract_flow_error(result) or "")


def is_circuit_open_detail(detail: Any) -> bool:
    from apps.search.services.public_surface_service import (
        is_circuit_open_detail as _is_circuit_open_detail,
    )

    return bool(_is_circuit_open_detail(detail))


def build_ai_provider_unavailable_payload(detail: Any) -> dict[str, Any]:
    from apps.search.services.public_surface_service import (
        build_ai_provider_unavailable_payload as _build_ai_provider_unavailable_payload,
    )

    return dict(_build_ai_provider_unavailable_payload(detail) or {})

__all__ = [
    "LeadGenResult",
    "LeadAction",
    "ResearchResult",
    "SearchHistory",
    "get_lead_by_id",
    "list_actioned_leads",
    "get_lead_action",
    "extract_flow_error",
    "is_circuit_open_detail",
    "build_ai_provider_unavailable_payload",
]
