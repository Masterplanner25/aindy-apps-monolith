#!/usr/bin/env bash
# Remove throwaway @local.test repro accounts and their child rows.
#
#   dry    (default) — run inside a transaction and ROLL BACK, printing what WOULD be deleted
#   apply            — same, committed
#
# EXCLUDES cap+* — that account holds the Track 2 capstone artifact (3 real tasks + 7 memory
# nodes from the Claude-planner run that reached `completed`). Pass KEEP_CAPSTONE=0 to include it.
# NEVER touches non-@local.test accounts (i.e. the real user).
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
PG="$(docker compose -f docker-compose.prod.yml ps -q postgres)"
MODE="${1:-dry}"
KEEP_CAPSTONE="${KEEP_CAPSTONE:-1}"

if [ "$KEEP_CAPSTONE" = "1" ]; then
  FILTER="email LIKE '%@local.test' AND email NOT LIKE 'cap+%'"
  echo "### scope: all @local.test EXCEPT cap+* (capstone preserved)"
else
  FILTER="email LIKE '%@local.test'"
  echo "### scope: ALL @local.test INCLUDING cap+* (capstone will be destroyed)"
fi
[ "$MODE" = "apply" ] && END="COMMIT" || END="ROLLBACK"
echo "### mode: $MODE  (ends with $END)"
echo

docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -v ON_ERROR_STOP=1 <<SQL
BEGIN;

DO \$\$
DECLARE
  r RECORD; target_ids uuid[]; n bigint; total bigint := 0;
BEGIN
  SELECT array_agg(id) INTO target_ids FROM users WHERE $FILTER;
  IF target_ids IS NULL THEN
    RAISE NOTICE 'no matching accounts — nothing to do';
    RETURN;
  END IF;
  RAISE NOTICE 'targeting % account(s)', array_length(target_ids,1);

  FOR r IN
    SELECT DISTINCT tc.table_name, kcu.column_name
      FROM information_schema.table_constraints tc
      JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
      JOIN information_schema.constraint_column_usage ccu
        ON tc.constraint_name = ccu.constraint_name
     WHERE tc.constraint_type='FOREIGN KEY'
       AND ccu.table_name='users'
       AND tc.table_name <> 'users'
  LOOP
    EXECUTE format('DELETE FROM %I WHERE %I = ANY(\$1)', r.table_name, r.column_name)
      USING target_ids;
    GET DIAGNOSTICS n = ROW_COUNT;
    total := total + n;
    IF n > 0 THEN RAISE NOTICE '  % rows <- %.%', n, r.table_name, r.column_name; END IF;
  END LOOP;

  DELETE FROM users WHERE id = ANY(target_ids);
  GET DIAGNOSTICS n = ROW_COUNT;
  RAISE NOTICE 'child rows deleted: %', total;
  RAISE NOTICE 'users deleted: %', n;
END \$\$;

-- what survives
SELECT email, created_at FROM users ORDER BY created_at;

$END;
SQL
