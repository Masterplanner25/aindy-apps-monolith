#!/usr/bin/env bash
# The app self-reports render errors to /client/error (ErrorBoundary.componentDidCatch).
# Find what it recorded — that's the real stack, instead of guessing from the source.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"; PG="$(dc ps -q postgres)"

echo "########## api log: /client/error posts + surrounding detail ##########"
docker logs "$API" --since 45m 2>&1 | grep -iE "client/error|client_error|componentStack|ErrorBoundary" | tail -20

echo
echo "########## where does the runtime persist client errors? ##########"
docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -tAc \
"SELECT table_name FROM information_schema.tables
  WHERE table_schema='public' AND (table_name ILIKE '%client%' OR table_name ILIKE '%error%'
     OR table_name ILIKE '%system_event%') ORDER BY 1;"

echo
echo "########## recent system_events that look like client errors ##########"
docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
"SELECT column_name FROM information_schema.columns WHERE table_name='system_events' ORDER BY ordinal_position;"
