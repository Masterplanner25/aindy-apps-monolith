"""add freelance pricing-recommendation outcome columns (learned pricing)

Records the realized-revenue verdict on each applied price change: after an observation
window the change is scored on expected revenue per lead (baseline_price × acceptance_rate)
vs its signals snapshot, a degraded change is auto-reverted, and the verdict feeds a learned
per-service revenue-direction bias. Additive + guarded (inspector has_column) so it is
idempotent on existing/fresh DBs alike.

Revision ID: aa11bb22cc33
Revises: a8b9c0d1e2f3
Create Date: 2026-07-19 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "aa11bb22cc33"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "freelance_pricing_recommendations"
_COLUMNS = (
    ("outcome", lambda: sa.Column("outcome", sa.String(length=16), nullable=True)),
    ("outcome_delta", lambda: sa.Column("outcome_delta", sa.Float(), nullable=True)),
    ("outcome_snapshot", lambda: sa.Column("outcome_snapshot", sa.JSON(), nullable=True)),
    ("evaluated_at", lambda: sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True)),
)


def _has_column(bind, table: str, column: str) -> bool:
    insp = inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in inspect(bind).get_table_names():
        return
    for name, make_column in _COLUMNS:
        if not _has_column(bind, _TABLE, name):
            op.add_column(_TABLE, make_column())
    if _has_column(bind, _TABLE, "outcome"):
        existing = {ix["name"] for ix in inspect(bind).get_indexes(_TABLE)}
        if "ix_freelance_pricing_recommendations_outcome" not in existing:
            op.create_index(
                "ix_freelance_pricing_recommendations_outcome", _TABLE, ["outcome"], unique=False
            )


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in inspect(bind).get_table_names():
        return
    existing = {ix["name"] for ix in inspect(bind).get_indexes(_TABLE)}
    if "ix_freelance_pricing_recommendations_outcome" in existing:
        op.drop_index("ix_freelance_pricing_recommendations_outcome", table_name=_TABLE)
    for name, _ in reversed(_COLUMNS):
        if _has_column(bind, _TABLE, name):
            op.drop_column(_TABLE, name)
