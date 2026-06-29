"""
Public surface for the search domain.
Consumers: freelance
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.search.models import LeadGenResult, ResearchResult, SearchHistory

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
    "ResearchResult",
    "SearchHistory",
    "get_lead_by_id",
    "extract_flow_error",
    "is_circuit_open_detail",
    "build_ai_provider_unavailable_payload",
]
