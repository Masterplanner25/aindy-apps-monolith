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

# Optional runtime pre-serve hook (runs before schema bootstrap).
if [ -n "${PRE_SERVE_CMD}" ]; then
  echo "[entrypoint] pre-serve: ${PRE_SERVE_CMD}"
  sh -c "${PRE_SERVE_CMD}"
fi

# Schema bootstrap (APP-DEPLOY-1). A plain `alembic upgrade head` on a FRESH DB replays the
# 100+ pre-split revisions that build the runtime-owned tables at a drifted schema, which
# `aindy-runtime serve`'s startup guard then rejects. deploy_bootstrap.py does the right thing:
#   fresh DB    -> create_all from packaged metadata (runtime tables match the guard) + stamp head
#   existing DB -> alembic upgrade head (incremental app migrations)
# See scripts/deploy_bootstrap.py and TECH_DEBT APP-DEPLOY-1.
echo "[entrypoint] schema bootstrap: python scripts/deploy_bootstrap.py"
python scripts/deploy_bootstrap.py

# Serve. `aindy-runtime serve` binds AINDY_HOST:AINDY_PORT and self-migrates the runtime schema;
# from this repo root it discovers ./aindy_plugins.json -> apps.bootstrap (app profile).
echo "[entrypoint] starting: $*"
exec "$@"
