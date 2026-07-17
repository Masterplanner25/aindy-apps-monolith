"""add freelance pricing tables (Revenue Intelligence Loop)

Adds ``freelance_service_prices`` (the studio's default price per service type — the
apply target) and ``freelance_pricing_recommendations`` (the tracked, revertible
recommendation audit) that back the Freelance Revenue Intelligence Loop: feedback +
revenue history -> a bounded pricing recommendation -> an applied, revertible default.

All operations are inspector-guarded (IF NOT EXISTS semantics) so the migration is
idempotent. Foreign keys are only created on engines that support ALTER-add-FK
(production is PostgreSQL; SQLite skips them).

Revision ID: b8d9e0f1a2c3
Revises: a7c8d9e0f1a2
Create Date: 2026-07-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "b8d9e0f1a2c3"
down_revision: Union[str, None] = "a7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    if not inspector.has_table("freelance_service_prices"):
        op.create_table(
            "freelance_service_prices",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=True),
            sa.Column("service_type", sa.String(), nullable=False),
            sa.Column("current_price", sa.Float(), nullable=False, server_default="0"),
            sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            *([] if is_sqlite else [sa.ForeignKeyConstraint(["user_id"], ["users.id"])]),
        )

    sp_indexes = (
        {ix["name"] for ix in inspector.get_indexes("freelance_service_prices")}
        if inspector.has_table("freelance_service_prices")
        else set()
    )
    if "ix_freelance_service_prices_id" not in sp_indexes:
        op.create_index(op.f("ix_freelance_service_prices_id"), "freelance_service_prices", ["id"], unique=False)
    if "ix_freelance_service_prices_user_id" not in sp_indexes:
        op.create_index(op.f("ix_freelance_service_prices_user_id"), "freelance_service_prices", ["user_id"], unique=False)
    if "ix_freelance_service_prices_service_type" not in sp_indexes:
        op.create_index(op.f("ix_freelance_service_prices_service_type"), "freelance_service_prices", ["service_type"], unique=False)
    if "ux_freelance_service_prices_user_service" not in sp_indexes:
        op.create_index(
            "ux_freelance_service_prices_user_service",
            "freelance_service_prices",
            ["user_id", "service_type"],
            unique=True,
        )

    if not inspector.has_table("freelance_pricing_recommendations"):
        op.create_table(
            "freelance_pricing_recommendations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=True),
            sa.Column("service_type", sa.String(), nullable=False),
            sa.Column("sample_size", sa.Integer(), nullable=True),
            sa.Column("baseline_price", sa.Float(), nullable=True),
            sa.Column("recommended_price", sa.Float(), nullable=True),
            sa.Column("multiplier", sa.Float(), nullable=True),
            sa.Column("direction", sa.String(length=16), nullable=True),
            sa.Column("rationale", sa.String(), nullable=True),
            sa.Column("signals", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="recommended"),
            sa.Column("prior_price", sa.Float(), nullable=True),
            sa.Column("trigger", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            *([] if is_sqlite else [sa.ForeignKeyConstraint(["user_id"], ["users.id"])]),
        )

    pr_indexes = (
        {ix["name"] for ix in inspector.get_indexes("freelance_pricing_recommendations")}
        if inspector.has_table("freelance_pricing_recommendations")
        else set()
    )
    if "ix_freelance_pricing_recommendations_id" not in pr_indexes:
        op.create_index(op.f("ix_freelance_pricing_recommendations_id"), "freelance_pricing_recommendations", ["id"], unique=False)
    if "ix_freelance_pricing_recommendations_user_id" not in pr_indexes:
        op.create_index(op.f("ix_freelance_pricing_recommendations_user_id"), "freelance_pricing_recommendations", ["user_id"], unique=False)
    if "ix_freelance_pricing_recommendations_service_type" not in pr_indexes:
        op.create_index(op.f("ix_freelance_pricing_recommendations_service_type"), "freelance_pricing_recommendations", ["service_type"], unique=False)
    if "ix_freelance_pricing_recommendations_status" not in pr_indexes:
        op.create_index(op.f("ix_freelance_pricing_recommendations_status"), "freelance_pricing_recommendations", ["status"], unique=False)
    if "ix_freelance_pricing_recommendations_created_at" not in pr_indexes:
        op.create_index(op.f("ix_freelance_pricing_recommendations_created_at"), "freelance_pricing_recommendations", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("freelance_pricing_recommendations"):
        op.drop_table("freelance_pricing_recommendations")
    if inspector.has_table("freelance_service_prices"):
        op.drop_table("freelance_service_prices")
