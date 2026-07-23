#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
PG="$(docker compose -f docker-compose.prod.yml ps -q postgres)"
docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
"SELECT t.name, t.status FROM tasks t JOIN users u ON t.user_id = u.id
  WHERE u.email LIKE 'cap+%' ORDER BY t.id;"
