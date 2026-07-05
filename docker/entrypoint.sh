#!/usr/bin/env sh
# Container entrypoint for the aindy-apps-monolith server image.
# Applies the app-owned schema, then execs the serving command (CMD = `aindy-runtime serve`).
#
# There are TWO Alembic version lines behind a deployed app-profile database:
#   - alembic_version_runtime : runtime-owned tables. The runtime owns and applies these
#                               itself (its `aindy-runtime init` compose runs only
#                               `aindy-runtime serve` with no migration step), so there is no
#                               separate runtime-migrate command to call here.
#   - alembic_version         : app-owned tables (this repo's alembic/alembic, 139 revisions).
set -e

# App-owned schema. Runs from the repo root; alembic.ini -> script_location alembic/alembic.
# NOTE (APP-DEPLOY-1): ordering vs the runtime's boot-time self-migration is unconfirmed —
# if an app revision FKs a runtime-owned table, the runtime schema must exist first. Set
# PRE_SERVE_CMD to a runtime pre-serve migrate/prepare step if the runtime deploy contract
# provides one.
if [ -n "${PRE_SERVE_CMD}" ]; then
  echo "[entrypoint] pre-serve: ${PRE_SERVE_CMD}"
  sh -c "${PRE_SERVE_CMD}"
fi

echo "[entrypoint] app migrations: alembic upgrade head"
alembic upgrade head

# Serve. `aindy-runtime serve` binds AINDY_HOST:AINDY_PORT and self-migrates the runtime schema;
# from this repo root it discovers ./aindy_plugins.json -> apps.bootstrap (app profile).
echo "[entrypoint] starting: $*"
exec "$@"
