#!/usr/bin/env bash
# READ-ONLY preview before any delete. Shows exactly which accounts match the cleanup
# pattern, what each owns, and confirms the real account is out of scope.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
PG="$(docker compose -f docker-compose.prod.yml ps -q postgres)"
Q() { docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c "$1"; }

echo "########## accounts MATCHING the cleanup pattern (would be deleted) ##########"
Q "SELECT email, created_at FROM users WHERE email LIKE '%@local.test' ORDER BY created_at;"

echo "########## accounts NOT matching (would be kept) ##########"
Q "SELECT email, created_at FROM users WHERE email NOT LIKE '%@local.test' ORDER BY created_at;"

echo "########## what each matching account owns ##########"
Q "SELECT u.email,
          (SELECT count(*) FROM memory_nodes m WHERE m.user_id = u.id)  AS memory_nodes,
          (SELECT count(*) FROM tasks t        WHERE t.user_id = u.id)  AS tasks
     FROM users u
    WHERE u.email LIKE '%@local.test'
    ORDER BY 3 DESC, 2 DESC;"

echo "########## every table with a FK to users (delete must handle these) ##########"
Q "SELECT tc.table_name, kcu.column_name, rc.delete_rule
     FROM information_schema.table_constraints tc
     JOIN information_schema.key_column_usage kcu   ON tc.constraint_name = kcu.constraint_name
     JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
     JOIN information_schema.referential_constraints rc  ON tc.constraint_name = rc.constraint_name
    WHERE tc.constraint_type='FOREIGN KEY' AND ccu.table_name='users'
    ORDER BY rc.delete_rule, tc.table_name;"
