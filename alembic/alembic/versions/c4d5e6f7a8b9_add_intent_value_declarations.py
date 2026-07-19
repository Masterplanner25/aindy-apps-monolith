"""add intent_value_declarations (three-axis score model — Worth axis declared prior)

Adds the ``intent_value_declarations`` table — the user's declared worth for a task /
masterplan / project (the Worth axis's prior in the three-axis Infinity score model,
Phase A). Observability only; does not feed the canonical ``master_score``.

Inspector-guarded (IF NOT EXISTS semantics); the users FK is only added on engines that
support ALTER-add-FK (production is PostgreSQL; SQLite skips it).

Revision ID: c4d5e6f7a8b9
Revises: e7f8a9b0c1d2
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    if not inspector.has_table("intent_value_declarations"):
        op.create_table(
            "intent_value_declarations",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("target_type", sa.String(length=16), nullable=False),
            sa.Column("target_id", sa.String(), nullable=True),
            sa.Column("label", sa.String(), nullable=True),
            sa.Column("declared_value", sa.Float(), nullable=False, server_default="0"),
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="strategic"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            *([] if is_sqlite else [sa.ForeignKeyConstraint(["user_id"], ["users.id"])]),
        )

    indexes = (
        {ix["name"] for ix in inspector.get_indexes("intent_value_declarations")}
        if inspector.has_table("intent_value_declarations")
        else set()
    )
    for col in ("user_id", "target_type", "target_id", "created_at"):
        ix_name = f"ix_intent_value_declarations_{col}"
        if ix_name not in indexes:
            op.create_index(op.f(ix_name), "intent_value_declarations", [col], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("intent_value_declarations"):
        op.drop_table("intent_value_declarations")
