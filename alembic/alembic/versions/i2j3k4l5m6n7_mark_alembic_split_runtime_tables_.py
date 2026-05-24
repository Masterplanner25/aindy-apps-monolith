"""mark_alembic_split_runtime_tables_excluded

Revision ID: i2j3k4l5m6n7
Revises: ee244b96f4ff
Create Date: 2026-05-23

No-op marker migration that records the Alembic split point. As of this
revision, the 32 runtime-owned tables listed in alembic/alembic/env.py
(_RUNTIME_TABLES) are excluded from monolith autogenerate. All schema
changes to those tables must be made through aindy-runtime Alembic
migrations (aindy-runtime/alembic/versions/).

Migration governance:
- Monolith manages: app domain tables (tasks, analytics, arm, identity, etc.)
- Runtime manages: platform + infrastructure tables (users, execution_units,
  agents, flows, webhooks, platform_api_keys, etc.)
"""

from alembic import op


revision = 'i2j3k4l5m6n7'
down_revision = 'ee244b96f4ff'
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
