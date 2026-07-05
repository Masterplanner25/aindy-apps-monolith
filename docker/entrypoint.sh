#!/usr/bin/env sh
# Container entrypoint for the aindy-apps-monolith server image.
# Applies schema migrations, then execs the serving command (CMD).
#
# There are TWO Alembic version lines behind a deployed app-profile database:
#   - alembic_version_runtime : runtime-owned tables (aindy-runtime tree)
#   - alembic_version         : app-owned tables (this repo's alembic/alembic, 139 revisions)
set -e

# 1) Runtime-owned schema (alembic_version_runtime).
#    The runtime package owns its migration mechanism and deploy guidance
#    (see aindy-runtime's RUNTIME_ONLY_DEPLOYMENT). Because that command is defined by
#    the runtime deploy contract (and is not introspectable from the installed package),
#    it is injected here rather than hard-coded. Set RUNTIME_MIGRATE_CMD to the runtime's
#    documented migrate command, or leave it empty if the runtime self-migrates at boot.
#    Tracked for confirmation/hard-wiring in TECH_DEBT.md -> APP-DEPLOY-1.
if [ -n "${RUNTIME_MIGRATE_CMD}" ]; then
  echo "[entrypoint] runtime migrations: ${RUNTIME_MIGRATE_CMD}"
  sh -c "${RUNTIME_MIGRATE_CMD}"
else
  echo "[entrypoint] RUNTIME_MIGRATE_CMD not set — skipping runtime migrations (assuming runtime self-migrates or was migrated out-of-band)."
fi

# 2) App-owned schema. Runs from the repo root; alembic.ini -> script_location alembic/alembic.
echo "[entrypoint] app migrations: alembic upgrade head"
alembic upgrade head

# 3) Serve. The runtime discovers ./aindy_plugins.json -> apps.bootstrap during lifespan.
echo "[entrypoint] starting: $*"
exec "$@"
