#!/usr/bin/env bash
# Read-only: which account owns the memory nodes? That's the only valid repro target —
# an account with ~0 nodes has no recall fan-out, so it would pass the test falsely.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
PGCID="$(docker compose -f docker-compose.prod.yml ps -q postgres)"
docker exec -i "$PGCID" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
  "SELECT u.email, count(m.id) AS memory_nodes
     FROM users u LEFT JOIN memory_nodes m ON m.user_id = u.id
    GROUP BY u.email ORDER BY memory_nodes DESC;"
