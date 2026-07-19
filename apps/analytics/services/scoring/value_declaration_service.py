"""
Declared-worth CRUD — the Worth axis's user-declared prior (three-axis model, Phase A).

Lets a user declare what a task / masterplan / project is *worth* to them, independent of
realized revenue. Read into the three-axis snapshot's Worth component; never touches
canonical scoring.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id
from apps.analytics.value_declaration import (
    VALID_TARGET_TYPES,
    VALID_WORTH_KINDS,
    IntentValueDeclaration,
)

logger = logging.getLogger(__name__)


def record_value_declaration(
    db: Session,
    *,
    user_id,
    target_type: str,
    declared_value: float,
    target_id: str | None = None,
    label: str | None = None,
    kind: str = "strategic",
    note: str | None = None,
) -> dict[str, Any]:
    """Record (or update, per (user, target_type, target_id)) a declared worth."""
    uid = parse_user_id(user_id)
    if uid is None:
        raise ValueError("a valid user_id is required")
    target_type = (target_type or "").strip().lower()
    if target_type not in VALID_TARGET_TYPES:
        raise ValueError(f"target_type must be one of {sorted(VALID_TARGET_TYPES)}")
    kind = (kind or "strategic").strip().lower()
    if kind not in VALID_WORTH_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_WORTH_KINDS)}")
    try:
        value = float(declared_value)
    except (TypeError, ValueError):
        raise ValueError("declared_value must be a number")

    # Upsert on (user, target_type, target_id) when a target is given; else always insert.
    row = None
    if target_id:
        row = (
            db.query(IntentValueDeclaration)
            .filter(
                IntentValueDeclaration.user_id == uid,
                IntentValueDeclaration.target_type == target_type,
                IntentValueDeclaration.target_id == str(target_id),
            )
            .first()
        )
    created = False
    if row is None:
        row = IntentValueDeclaration(
            user_id=uid, target_type=target_type, target_id=(str(target_id) if target_id else None),
        )
        db.add(row)
        created = True
    row.declared_value = value
    row.kind = kind
    if label is not None:
        row.label = label
    if note is not None:
        row.note = note
    db.commit()
    db.refresh(row)
    return _serialize(row) | {"created": created}


def list_value_declarations(db: Session, user_id, *, limit: int = 100) -> list[dict[str, Any]]:
    uid = parse_user_id(user_id)
    if uid is None:
        return []
    rows = (
        db.query(IntentValueDeclaration)
        .filter(IntentValueDeclaration.user_id == uid)
        .order_by(IntentValueDeclaration.created_at.desc())
        .limit(max(1, min(int(limit or 100), 500)))
        .all()
    )
    return [_serialize(r) for r in rows]


def declared_worth_summary(db: Session, user_id) -> dict[str, Any]:
    """Total declared worth + a per-kind breakdown for the Worth axis."""
    uid = parse_user_id(user_id)
    if uid is None:
        return {"total": 0.0, "by_kind": {}, "count": 0}
    rows = (
        db.query(IntentValueDeclaration)
        .filter(IntentValueDeclaration.user_id == uid)
        .all()
    )
    by_kind: dict[str, float] = {}
    total = 0.0
    for r in rows:
        v = float(r.declared_value or 0.0)
        total += v
        by_kind[r.kind] = round(by_kind.get(r.kind, 0.0) + v, 2)
    return {"total": round(total, 2), "by_kind": by_kind, "count": len(rows)}


def _serialize(row: IntentValueDeclaration) -> dict[str, Any]:
    return {
        "id": row.id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "label": row.label,
        "declared_value": row.declared_value,
        "kind": row.kind,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
