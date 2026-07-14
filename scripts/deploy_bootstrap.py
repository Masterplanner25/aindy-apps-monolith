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

Ownership split (entrypoint)
----------------------------
The deploy entrypoint runs ``aindy-runtime bootstrap-schema`` FIRST (aindy-runtime>=1.7.0):
the runtime builds ITS own tables from packaged metadata and stamps ``alembic_version_runtime``.
This script then handles ONLY the app side:

* Fresh DB  -> ``Base.metadata.create_all`` (idempotent: the runtime-owned tables already exist
  from ``bootstrap-schema`` and are skipped, so this fills in the app-owned tables), then
  ``alembic stamp head`` so future app migrations apply incrementally instead of replaying the
  pre-split revisions.
* Existing DB -> ``alembic upgrade head`` (normal incremental app migrations; post-split
  revisions are app-owned only).

Fresh-vs-existing is keyed on the *app* ``alembic_version`` table (``bootstrap-schema`` stamps
the separate ``alembic_version_runtime`` line, so it does not affect this check). Running this
without ``bootstrap-schema`` first still works for the current pinned runtime (create_all builds
the runtime tables at the packaged schema so the guard passes) but leaves ``alembic_version_runtime``
unstamped — the entrypoint runs both so the runtime baseline is always present.

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
