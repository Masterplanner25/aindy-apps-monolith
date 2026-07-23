#!/usr/bin/env bash
# Read-only: does the live stack have any user accounts to run the login repro against?
# Prints emails + created_at only — no secrets, no writes.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
PGCID="$(docker compose -f docker-compose.prod.yml ps -q postgres)"
docker exec -i "$PGCID" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
  "SELECT email, created_at FROM users ORDER BY created_at DESC LIMIT 10;"
docker exec -i "$PGCID" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
  "SELECT count(*) AS user_count FROM users;"
docker exec -i "$PGCID" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
  "SELECT count(*) AS memory_node_count FROM memory_nodes;"
