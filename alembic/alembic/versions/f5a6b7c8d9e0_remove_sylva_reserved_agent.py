"""remove SYLVA reserved-agent seed row

The ``agents`` seed (migration a2ec23964f2c) reserved an inactive SYLVA namespace
(``agent-sylva-001``, is_active=false, "Future collaborative agent — reserved
namespace"). It was never activated and nothing references it (no ORM model, no
code, no tests). Remove the dead scaffolding.

Guarded (table-exists check) and idempotent (DELETE of an absent row is a no-op).

Revision ID: f5a6b7c8d9e0
Revises: d8e9f0a1b2c3
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("agents"):
        op.execute(sa.text("DELETE FROM agents WHERE id = 'agent-sylva-001'"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("agents"):
        op.execute(
            sa.text(
                """
                INSERT INTO agents
                    (id, name, agent_type, description, memory_namespace, is_active)
                VALUES
                    ('agent-sylva-001', 'SYLVA', 'custom',
                     'Future collaborative agent — reserved namespace',
                     'sylva', false)
                ON CONFLICT DO NOTHING
                """
            )
        )
