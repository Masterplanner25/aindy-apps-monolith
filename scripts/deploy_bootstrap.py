"""Deploy-time schema bootstrap for the app-profile server image (APP-DEPLOY-1).

Why this exists
---------------
The app's Alembic history contains 100+ pre-split revisions that explicitly build the
*runtime-owned* tables (``agent_runs``, ``execution_units``, ``users`` …) at the schema
they had before the aindy-runtime split. ``alembic/alembic/env.py`` only excludes those
tables from *autogenerate* (``include_object`` + the ``mark_alembic_split_runtime_tables_excluded``
marker) — replaying the historical revisions on a fresh DB still creates them at the drifted
schema, which ``aindy-runtime serve``'s startup schema guard correctly rejects
("Runtime-owned schema is incompatible with packaged metadata").

Correct bootstrap
-----------------
* Fresh DB  -> build the whole schema from the *packaged* metadata with
  ``Base.metadata.create_all`` (so the runtime-owned tables match aindy-runtime's current
  packaged schema and the guard passes), then ``alembic stamp head`` so future app-owned
  migrations apply incrementally instead of replaying the 139 historical revisions.
* Existing DB -> ``alembic upgrade head`` (normal incremental app migrations; post-split
  revisions are app-owned only).

Ownership note (see the runtime bootstrap-command request in TECH_DEBT APP-DEPLOY-1):
create_all does not stamp the runtime's own ``alembic_version_runtime`` line — the runtime
owns that. For the pinned runtime version the tables match packaged metadata so ``serve``
boots; a runtime-blessed ``bootstrap-schema`` command is the clean long-term path so future
runtime schema upgrades onto a create_all-built DB have a baseline.

Model loading mirrors ``alembic/alembic/env.py`` exactly (no full server boot).
"""
import subprocess
import sys

from sqlalchemy import inspect, text

# Populate Base.metadata the same way alembic/alembic/env.py does.
from AINDY.db.base import Base  # noqa: E402
import AINDY.db.model_registry  # noqa: E402,F401 — runtime-owned platform models
import apps.bootstrap  # noqa: E402
import AINDY.memory.memory_persistence  # noqa: E402,F401

apps.bootstrap.bootstrap_models()

from AINDY.db.database import engine  # noqa: E402


def main() -> int:
    # pgvector columns (e.g. memory_nodes.embedding) need the extension before create_all.
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    fresh = "alembic_version" not in inspect(engine).get_table_names()

    if fresh:
        print(
            "[deploy_bootstrap] fresh DB -> create_all (runtime tables at packaged schema) "
            "+ alembic stamp head",
            flush=True,
        )
        Base.metadata.create_all(bind=engine)
        subprocess.run(["alembic", "stamp", "head"], check=True)
    else:
        print("[deploy_bootstrap] existing DB -> alembic upgrade head", flush=True)
        subprocess.run(["alembic", "upgrade", "head"], check=True)

    print("[deploy_bootstrap] schema ready", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
