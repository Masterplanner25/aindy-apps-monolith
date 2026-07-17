"""add infinity expectation tables (learned REFLECT calibrator, Phase 0 shadow)

Adds ``infinity_expectation_models`` (one fitted ridge per decision_type) and
``infinity_expectation_predictions`` (the shadow ledger comparing learned vs
heuristic expected-score against the realized score). Pooled — no user FK. Nothing
here drives canonical scoring; the ledger is write-only observability behind the
``AINDY_INFINITY_LEARNED_SHADOW`` flag.

All operations are inspector-guarded (IF NOT EXISTS semantics) so the migration is
idempotent.

Revision ID: d8e9f0a1b2c3
Revises: b8d9e0f1a2c3
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "b8d9e0f1a2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("infinity_expectation_models"):
        op.create_table(
            "infinity_expectation_models",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("decision_type", sa.String(), nullable=False),
            sa.Column("coefficients", sa.JSON(), nullable=False),
            sa.Column("feature_keys", sa.JSON(), nullable=False),
            sa.Column("feature_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("holdout_mae", sa.Float(), nullable=True),
            sa.Column("trained_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    m_indexes = (
        {ix["name"] for ix in inspector.get_indexes("infinity_expectation_models")}
        if inspector.has_table("infinity_expectation_models")
        else set()
    )
    if "ix_infinity_expectation_models_decision_type" not in m_indexes:
        op.create_index(
            op.f("ix_infinity_expectation_models_decision_type"),
            "infinity_expectation_models",
            ["decision_type"],
            unique=True,
        )

    if not inspector.has_table("infinity_expectation_predictions"):
        op.create_table(
            "infinity_expectation_predictions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("loop_adjustment_id", sa.String(), nullable=True),
            sa.Column("decision_type", sa.String(), nullable=False),
            sa.Column("features", sa.JSON(), nullable=False),
            sa.Column("learned_expected", sa.Float(), nullable=True),
            sa.Column("heuristic_expected", sa.Float(), nullable=True),
            sa.Column("actual_score", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    p_indexes = (
        {ix["name"] for ix in inspector.get_indexes("infinity_expectation_predictions")}
        if inspector.has_table("infinity_expectation_predictions")
        else set()
    )
    if "ix_infinity_expectation_predictions_loop_adjustment_id" not in p_indexes:
        op.create_index(
            op.f("ix_infinity_expectation_predictions_loop_adjustment_id"),
            "infinity_expectation_predictions",
            ["loop_adjustment_id"],
            unique=False,
        )
    if "ix_infinity_expectation_predictions_decision_type" not in p_indexes:
        op.create_index(
            op.f("ix_infinity_expectation_predictions_decision_type"),
            "infinity_expectation_predictions",
            ["decision_type"],
            unique=False,
        )
    if "ix_infinity_expectation_predictions_created_at" not in p_indexes:
        op.create_index(
            op.f("ix_infinity_expectation_predictions_created_at"),
            "infinity_expectation_predictions",
            ["created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("infinity_expectation_predictions"):
        op.drop_table("infinity_expectation_predictions")
    if inspector.has_table("infinity_expectation_models"):
        op.drop_table("infinity_expectation_models")
