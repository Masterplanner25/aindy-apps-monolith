#!/usr/bin/env bash
# Read-only: 1246 total nodes but only 7 owned by a user — where do the rest live?
# If recall reads user-scoped rows only, an account with 0 nodes can't reproduce the fan-out.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
PGCID="$(docker compose -f docker-compose.prod.yml ps -q postgres)"
docker exec -i "$PGCID" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
  "SELECT (user_id IS NULL) AS user_id_is_null, count(*) FROM memory_nodes GROUP BY 1;"
