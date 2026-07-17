"""add arm_autotune_log

Adds the ``arm_autotune_log`` audit table backing ARM's self-tuning (Reflect ->
Adjust) loop: one row per auto-tune run records what the guarded consumer applied
from the suggestion engine's ``auto_apply_safe`` set, what it skipped and why, and
a full pre-change config snapshot so any run can be reverted exactly.

All operations are inspector-guarded (IF NOT EXISTS semantics) so the migration is
idempotent, consistent with the app/runtime migration rule.

Revision ID: f4a5b6c7d8e9
Revises: a1c2e3f4b5d6
Create Date: 2026-07-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, None] = "a1c2e3f4b5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("arm_autotune_log"):
        op.create_table(
            "arm_autotune_log",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("trigger", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column("applied", sa.JSON(), nullable=False),
            sa.Column("skipped", sa.JSON(), nullable=False),
            sa.Column("prior_config", sa.JSON(), nullable=False),
            sa.Column("resulting_config", sa.JSON(), nullable=False),
            sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
            sa.Column("reverted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_indexes = (
        {ix["name"] for ix in inspector.get_indexes("arm_autotune_log")}
        if inspector.has_table("arm_autotune_log")
        else set()
    )
    if "ix_arm_autotune_log_user_id" not in existing_indexes:
        op.create_index(op.f("ix_arm_autotune_log_user_id"), "arm_autotune_log", ["user_id"], unique=False)
    if "ix_arm_autotune_log_created_at" not in existing_indexes:
        op.create_index(op.f("ix_arm_autotune_log_created_at"), "arm_autotune_log", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("arm_autotune_log"):
        op.drop_table("arm_autotune_log")
