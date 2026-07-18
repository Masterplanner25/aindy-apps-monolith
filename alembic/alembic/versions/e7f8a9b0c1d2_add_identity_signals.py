"""add identity_signals (identity inference evidence model)

Adds the ``identity_signals`` table — weighted, provenance-tagged observation votes
behind each inferred identity dimension. Replaces rules-only single-observation flips
with an accumulating evidence base the inference engine aggregates by confidence.

Inspector-guarded (IF NOT EXISTS semantics); the users FK is only added on engines that
support ALTER-add-FK (production is PostgreSQL; SQLite skips it).

Revision ID: e7f8a9b0c1d2
Revises: c3d4e5f6a7b9
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "c3d4e5f6a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    if not inspector.has_table("identity_signals"):
        op.create_table(
            "identity_signals",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("dimension", sa.String(length=32), nullable=False),
            sa.Column("value", sa.String(length=64), nullable=False),
            sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
            sa.Column("event_type", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            *([] if is_sqlite else [sa.ForeignKeyConstraint(["user_id"], ["users.id"])]),
        )

    indexes = (
        {ix["name"] for ix in inspector.get_indexes("identity_signals")}
        if inspector.has_table("identity_signals")
        else set()
    )
    for col in ("user_id", "dimension", "value", "created_at"):
        ix_name = f"ix_identity_signals_{col}"
        if ix_name not in indexes:
            op.create_index(op.f(ix_name), "identity_signals", [col], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("identity_signals"):
        op.drop_table("identity_signals")
