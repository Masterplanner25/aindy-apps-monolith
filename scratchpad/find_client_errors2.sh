#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
PG="$(dc ps -q postgres)"
Q() { docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" "$@"; }

echo "########## recent system_event types (last 2h) ##########"
Q -c "SELECT type, count(*) FROM system_events WHERE timestamp > now() - interval '2 hours'
      GROUP BY 1 ORDER BY 2 DESC LIMIT 15;"

echo "########## anything client/error/ui flavoured ##########"
Q -c "SELECT type, source, left(payload::text, 400) AS payload, timestamp
        FROM system_events
       WHERE (type ILIKE '%client%' OR type ILIKE '%error%' OR source ILIKE '%client%')
         AND timestamp > now() - interval '6 hours'
       ORDER BY timestamp DESC LIMIT 8;"
