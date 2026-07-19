"""add search lead-action outcome + segment columns (learned execution close)

Records the conversion verdict on each actioned lead so the Execution Layer can learn:
after an observation window a non-reverted action is judged on its in-domain conversion
signal (a `convert`/thumbs_up on the lead's url in SearchResultFeedback), and a segment
(lead_query) whose actioned leads consistently fail to convert is auto-suppressed forward.
Additive + guarded (inspector has_column) so it is idempotent on existing/fresh DBs alike.

Revision ID: bb22cc33dd44
Revises: aa11bb22cc33
Create Date: 2026-07-19 17:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "bb22cc33dd44"
down_revision: Union[str, None] = "aa11bb22cc33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "lead_actions"
_COLUMNS = (
    ("lead_query", lambda: sa.Column("lead_query", sa.String(), nullable=True)),
    ("outcome", lambda: sa.Column("outcome", sa.String(length=16), nullable=True)),
    ("outcome_signal", lambda: sa.Column("outcome_signal", sa.Float(), nullable=True)),
    ("evaluated_at", lambda: sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True)),
)
_INDEXES = (
    ("ix_lead_actions_lead_query", "lead_query"),
    ("ix_lead_actions_outcome", "outcome"),
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
    existing = {ix["name"] for ix in inspect(bind).get_indexes(_TABLE)}
    for index_name, column in _INDEXES:
        if _has_column(bind, _TABLE, column) and index_name not in existing:
            op.create_index(index_name, _TABLE, [column], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in inspect(bind).get_table_names():
        return
    existing = {ix["name"] for ix in inspect(bind).get_indexes(_TABLE)}
    for index_name, _ in _INDEXES:
        if index_name in existing:
            op.drop_index(index_name, table_name=_TABLE)
    for name, _ in reversed(_COLUMNS):
        if _has_column(bind, _TABLE, name):
            op.drop_column(_TABLE, name)
