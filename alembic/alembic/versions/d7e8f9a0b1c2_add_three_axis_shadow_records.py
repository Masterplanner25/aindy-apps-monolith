"""add three_axis_shadow_records (three-axis score model — Phase B shadow ledger)

Adds the ``three_axis_shadow_records`` table — the Volume/Worth/Trajectory time-series
logged next to ``master_score`` when ``AINDY_INFINITY_THREE_AXIS_SHADOW`` is on. Drives
nothing; observability only.

Inspector-guarded (IF NOT EXISTS semantics); the users FK is only added on engines that
support ALTER-add-FK (production is PostgreSQL; SQLite skips it).

Revision ID: d7e8f9a0b1c2
Revises: c4d5e6f7a8b9
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    if not inspector.has_table("three_axis_shadow_records"):
        op.create_table(
            "three_axis_shadow_records",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("master_score", sa.Float(), nullable=True),
            sa.Column("volume_score", sa.Float(), nullable=True),
            sa.Column("worth_score", sa.Float(), nullable=True),
            sa.Column("trajectory_score", sa.Float(), nullable=True),
            sa.Column("effort_hours", sa.Float(), nullable=True),
            sa.Column("completed_count", sa.Integer(), nullable=True),
            sa.Column("declared_total", sa.Float(), nullable=True),
            sa.Column("realized_revenue", sa.Float(), nullable=True),
            sa.Column("mean_pace_ratio", sa.Float(), nullable=True),
            sa.Column("trigger_event", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            *([] if is_sqlite else [sa.ForeignKeyConstraint(["user_id"], ["users.id"])]),
        )

    indexes = (
        {ix["name"] for ix in inspector.get_indexes("three_axis_shadow_records")}
        if inspector.has_table("three_axis_shadow_records")
        else set()
    )
    for col in ("user_id", "trigger_event", "created_at"):
        ix_name = f"ix_three_axis_shadow_records_{col}"
        if ix_name not in indexes:
            op.create_index(op.f(ix_name), "three_axis_shadow_records", [col], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("three_axis_shadow_records"):
        op.drop_table("three_axis_shadow_records")
