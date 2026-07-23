#!/usr/bin/env bash
# Post-cleanup verification: accounts left, capstone artifact intact, no orphaned rows.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
PG="$(docker compose -f docker-compose.prod.yml ps -q postgres)"
Q() { docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c "$1"; }

echo "########## accounts remaining ##########"
Q "SELECT email, created_at FROM users ORDER BY created_at;"

echo "########## capstone artifact still intact? ##########"
Q "SELECT u.email,
          (SELECT count(*) FROM tasks t        WHERE t.user_id = u.id) AS tasks,
          (SELECT count(*) FROM memory_nodes m WHERE m.user_id = u.id) AS memory_nodes
     FROM users u WHERE u.email LIKE 'cap+%';"

echo "########## the 3 capstone tasks ##########"
Q "SELECT t.title, t.status
     FROM tasks t JOIN users u ON t.user_id = u.id
    WHERE u.email LIKE 'cap+%' ORDER BY t.id;"

echo "########## memory corpus (global rows untouched) ##########"
Q "SELECT (user_id IS NULL) AS is_global, count(*) FROM memory_nodes GROUP BY 1;"
