"""add search_result_feedback (Search v4 outcome signal)

Adds the ``search_result_feedback`` table — implicit + explicit feedback on search
results, deduped per (user, query, result_ref, signal) and aggregated into a per-query
outcome weight for future ranking (the §8 feedback loop).

Inspector-guarded (IF NOT EXISTS semantics); the users FK is only added on engines that
support ALTER-add-FK (production is PostgreSQL; SQLite skips it).

Revision ID: c3d4e5f6a7b9
Revises: f5a6b7c8d9e0
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b9"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    if not inspector.has_table("search_result_feedback"):
        op.create_table(
            "search_result_feedback",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=True),
            sa.Column("query", sa.String(), nullable=False),
            sa.Column("history_id", sa.String(), nullable=True),
            sa.Column("result_ref", sa.String(), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("signal", sa.String(length=32), nullable=False),
            sa.Column("weight", sa.Float(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            *([] if is_sqlite else [sa.ForeignKeyConstraint(["user_id"], ["users.id"])]),
        )

    indexes = (
        {ix["name"] for ix in inspector.get_indexes("search_result_feedback")}
        if inspector.has_table("search_result_feedback")
        else set()
    )
    for col in ("user_id", "query", "history_id", "result_ref", "created_at"):
        ix_name = f"ix_search_result_feedback_{col}"
        if ix_name not in indexes:
            op.create_index(op.f(ix_name), "search_result_feedback", [col], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("search_result_feedback"):
        op.drop_table("search_result_feedback")
