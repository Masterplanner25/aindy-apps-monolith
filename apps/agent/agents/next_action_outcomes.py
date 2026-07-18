"""
Next-Action dispatch-outcome read (FR-3 adoption).

The completion hook records the app's chosen NextAction as a ``next_action.chosen``
event (Deliverable B). When autonomous acting is enabled (``AINDY_NEXT_ACTION_ACTING``,
default off) the runtime records exactly one ``next_action.dispatched`` outcome per
chosen ``trigger_execution`` — linked to the CHOSEN via ``parent_event_id`` — carrying the
``disposition`` (enqueued / declined_* / followup_*). This module reads that outcome back
so the autonomous-acting loop is observable: the visibility an operator needs to soak the
behavior before flipping the acting flag on.

Read-only over the runtime ``system_events`` ledger; the runtime owns the emission.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from AINDY.core.system_event_types import SystemEventTypes
from AINDY.db.models.system_event import SystemEvent
from AINDY.platform_layer.user_ids import parse_user_id

logger = logging.getLogger(__name__)

_DISPATCHED = SystemEventTypes.NEXT_ACTION_DISPATCHED  # "next_action.dispatched"
_TRUTHY = {"1", "true", "yes", "on"}


def acting_enabled() -> bool:
    """Whether the runtime's autonomous Next-Action acting is switched on (a hint).

    The read works regardless — with acting off there are simply no dispatch outcomes to
    read yet. Surfaced so an operator can tell ``[]`` "acting is off" from ``[]`` "on but
    nothing dispatched".
    """
    return os.environ.get("AINDY_NEXT_ACTION_ACTING", "").strip().lower() in _TRUTHY


def _chosen_summary(parent: SystemEvent | None) -> dict[str, Any] | None:
    if parent is None:
        return None
    cp = parent.payload or {}
    return {
        "event_id": str(parent.id),
        "action": cp.get("action") or cp.get("next_action") or cp.get("decision"),
        "reason": cp.get("reason"),
    }


def _outcome_row(event: SystemEvent, chosen_by_id: dict) -> dict[str, Any]:
    payload = event.payload or {}
    parent = chosen_by_id.get(event.parent_event_id) if event.parent_event_id else None
    return {
        "event_id": str(event.id),
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "trace_id": event.trace_id,
        "disposition": payload.get("disposition"),
        "dispatched": bool(payload.get("dispatched")),
        "reason": payload.get("reason"),
        "objective_preview": payload.get("objective_preview"),
        "chain_depth": payload.get("chain_depth"),
        "followup_run_id": payload.get("followup_run_id"),
        "followup_status": payload.get("followup_status"),
        "chosen": _chosen_summary(parent),
    }


def get_dispatch_outcomes(db, *, user_id, trace_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Recent Next-Action dispatch outcomes for a user (optionally one trace/run).

    Returns ``{outcomes, summary, count, acting_enabled}`` where ``summary`` is a
    per-disposition count — the at-a-glance soak signal (how many ``enqueued`` vs
    ``declined_admission`` vs ``followup_executed`` …). Newest first.
    """
    uid = parse_user_id(user_id)
    if uid is None:
        return {"outcomes": [], "summary": {}, "count": 0, "acting_enabled": acting_enabled()}

    query = db.query(SystemEvent).filter(
        SystemEvent.type == _DISPATCHED,
        SystemEvent.user_id == uid,
    )
    if trace_id:
        query = query.filter(SystemEvent.trace_id == str(trace_id))
    capped = max(1, min(int(limit or 20), 200))
    events = query.order_by(SystemEvent.timestamp.desc()).limit(capped).all()

    # Batch-fetch the parent CHOSEN events so the CHOSEN -> DISPATCHED chain is shown
    # without an N+1 query.
    parent_ids = [e.parent_event_id for e in events if e.parent_event_id]
    chosen_by_id: dict[Any, SystemEvent] = {}
    if parent_ids:
        for row in db.query(SystemEvent).filter(SystemEvent.id.in_(parent_ids)).all():
            chosen_by_id[row.id] = row

    outcomes = [_outcome_row(e, chosen_by_id) for e in events]
    summary: dict[str, int] = {}
    for outcome in outcomes:
        key = outcome["disposition"] or "unknown"
        summary[key] = summary.get(key, 0) + 1

    return {
        "outcomes": outcomes,
        "summary": summary,
        "count": len(outcomes),
        "acting_enabled": acting_enabled(),
    }
