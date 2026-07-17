"""Data access for ARM auto-tune audit rows (arm_autotune_log)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.arm.models import ArmAutoTuneLog


def _as_uuid(log_id: Any) -> UUID:
    return log_id if isinstance(log_id, UUID) else UUID(str(log_id))


def create_log(
    db: Session,
    *,
    user_id: str,
    trigger: str,
    applied: list[dict],
    skipped: list[dict],
    prior_config: dict,
    resulting_config: dict,
    metrics_snapshot: dict,
) -> ArmAutoTuneLog:
    row = ArmAutoTuneLog(
        user_id=str(user_id),
        trigger=trigger,
        applied=applied,
        skipped=skipped,
        prior_config=prior_config,
        resulting_config=resulting_config,
        metrics_snapshot=metrics_snapshot,
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
    except SQLAlchemyError:
        db.rollback()
        raise
    return row


def get_log(db: Session, log_id: Any, user_id: str | None = None) -> ArmAutoTuneLog | None:
    query = db.query(ArmAutoTuneLog).filter(ArmAutoTuneLog.id == _as_uuid(log_id))
    if user_id is not None:
        query = query.filter(ArmAutoTuneLog.user_id == str(user_id))
    return query.first()


def list_logs(db: Session, user_id: str, limit: int = 20) -> list[ArmAutoTuneLog]:
    return (
        db.query(ArmAutoTuneLog)
        .filter(ArmAutoTuneLog.user_id == str(user_id))
        .order_by(ArmAutoTuneLog.created_at.desc())
        .limit(limit)
        .all()
    )


def recent_changed_keys(db: Session, user_id: str, since: datetime) -> set[str]:
    """Params auto-applied (and not reverted) since ``since`` — the cooldown set."""
    rows = (
        db.query(ArmAutoTuneLog)
        .filter(
            ArmAutoTuneLog.user_id == str(user_id),
            ArmAutoTuneLog.reverted.is_(False),
            ArmAutoTuneLog.created_at >= since,
        )
        .all()
    )
    keys: set[str] = set()
    for row in rows:
        for change in row.applied or []:
            param = change.get("param")
            if param:
                keys.add(param)
    return keys


def mark_reverted(db: Session, log_id: Any, user_id: str | None = None) -> ArmAutoTuneLog | None:
    row = get_log(db, log_id, user_id=user_id)
    if row is None:
        return None
    row.reverted = True
    row.reverted_at = datetime.now(timezone.utc)
    try:
        db.commit()
        db.refresh(row)
    except SQLAlchemyError:
        db.rollback()
        raise
    return row
