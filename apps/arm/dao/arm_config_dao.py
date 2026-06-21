from __future__ import annotations

from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.arm.models import ArmConfig


def _config_key(user_id=None) -> str:
    return str(user_id) if user_id is not None else "default"


def get_config(db: Session, user_id=None) -> ArmConfig | None:
    return db.query(ArmConfig).filter(ArmConfig.id == _config_key(user_id)).first()


def upsert_config(db: Session, user_id=None, **fields: Any) -> ArmConfig:
    row_key = _config_key(user_id)
    config = db.query(ArmConfig).filter(ArmConfig.id == row_key).first()
    if config is None:
        config = ArmConfig(id=row_key)
        db.add(config)

    for field_name, value in fields.items():
        if hasattr(ArmConfig, field_name):
            setattr(config, field_name, value)

    try:
        db.commit()
        db.refresh(config)
    except SQLAlchemyError:
        db.rollback()
        raise
    return config
