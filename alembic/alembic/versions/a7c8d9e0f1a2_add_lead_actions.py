"""add lead_actions (Search Execution Layer)

Adds the ``lead_actions`` table — the act-on-insight artifact for the Search
Execution Layer. One row per lead the guarded consumer decides to pursue, carrying
the outreach draft, the qualifying decision, and revert state.

All operations are inspector-guarded (IF NOT EXISTS semantics) so the migration is
idempotent, consistent with the app/runtime migration rule. Foreign keys are only
created on engines that support ALTER-add-FK (production is PostgreSQL; SQLite skips).

Revision ID: a7c8d9e0f1a2
Revises: f4a5b6c7d8e9
Create Date: 2026-07-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "a7c8d9e0f1a2"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    if not inspector.has_table("lead_actions"):
        op.create_table(
            "lead_actions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=True),
            sa.Column("lead_id", sa.Integer(), nullable=True),
            sa.Column("company", sa.String(), nullable=True),
            sa.Column("url", sa.String(), nullable=True),
            sa.Column("channel", sa.String(length=16), nullable=True, server_default="draft"),
            sa.Column("status", sa.String(length=16), nullable=True, server_default="drafted"),
            sa.Column("draft_subject", sa.String(), nullable=True),
            sa.Column("draft_body", sa.Text(), nullable=True),
            sa.Column("decision_score", sa.Float(), nullable=True),
            sa.Column("decision_reason", sa.String(), nullable=True),
            sa.Column("trigger", sa.String(length=16), nullable=True, server_default="manual"),
            sa.Column("note", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            *(
                []
                if is_sqlite
                else [
                    sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
                    sa.ForeignKeyConstraint(["lead_id"], ["leadgen_results.id"], ondelete="SET NULL"),
                ]
            ),
        )

    existing_indexes = (
        {ix["name"] for ix in inspector.get_indexes("lead_actions")}
        if inspector.has_table("lead_actions")
        else set()
    )
    if "ix_lead_actions_id" not in existing_indexes:
        op.create_index(op.f("ix_lead_actions_id"), "lead_actions", ["id"], unique=False)
    if "ix_lead_actions_user_id" not in existing_indexes:
        op.create_index(op.f("ix_lead_actions_user_id"), "lead_actions", ["user_id"], unique=False)
    if "ix_lead_actions_lead_id" not in existing_indexes:
        op.create_index(op.f("ix_lead_actions_lead_id"), "lead_actions", ["lead_id"], unique=False)
    if "ix_lead_actions_status" not in existing_indexes:
        op.create_index(op.f("ix_lead_actions_status"), "lead_actions", ["status"], unique=False)
    if "ix_lead_actions_created_at" not in existing_indexes:
        op.create_index(op.f("ix_lead_actions_created_at"), "lead_actions", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("lead_actions"):
        op.drop_table("lead_actions")
