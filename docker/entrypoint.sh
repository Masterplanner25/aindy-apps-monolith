#!/usr/bin/env sh
# Container entrypoint for the aindy-apps-monolith server image.
# Bootstraps schema by OWNERSHIP, then execs the serving command (CMD = `aindy-runtime serve`).
#
# Two Alembic version lines back a deployed app-profile database, each owned by its side:
#   - alembic_version_runtime : runtime-owned tables. Built + stamped by the runtime's own
#                               `aindy-runtime bootstrap-schema` command (aindy-runtime>=1.7.0).
#   - alembic_version         : app-owned tables (this repo's alembic/alembic).
set -e

# Optional runtime pre-serve hook (runs before schema bootstrap).
if [ -n "${PRE_SERVE_CMD}" ]; then
  echo "[entrypoint] pre-serve: ${PRE_SERVE_CMD}"
  sh -c "${PRE_SERVE_CMD}"
fi

# Schema bootstrap (APP-DEPLOY-1) — clean ownership split:
#   1. Runtime builds ITS tables from packaged metadata and stamps alembic_version_runtime,
#      so `aindy-runtime serve`'s startup guard accepts the schema and a later runtime schema
#      upgrade has a baseline. Idempotent (safe on existing DBs; back-fills the runtime baseline
#      on DBs first built by the older app-side create_all-only path).
#   2. App builds ITS tables: fresh DB -> create_all (runtime tables already exist, skipped) +
#      `alembic stamp head`; existing DB -> `alembic upgrade head`. See scripts/deploy_bootstrap.py.
# A bare `alembic upgrade head` on a FRESH DB would replay the 100+ pre-split revisions that build
# the runtime-owned tables at a drifted schema, which the guard rejects — hence this split.
echo "[entrypoint] runtime schema: aindy-runtime bootstrap-schema"
aindy-runtime bootstrap-schema
echo "[entrypoint] app schema: python scripts/deploy_bootstrap.py"
python scripts/deploy_bootstrap.py

# Serve. `aindy-runtime serve` binds AINDY_HOST:AINDY_PORT and self-migrates the runtime schema;
# from this repo root it discovers ./aindy_plugins.json -> apps.bootstrap (app profile).
echo "[entrypoint] starting: $*"
exec "$@"
