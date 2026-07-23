#!/usr/bin/env bash
# RT-MEMTXN-LEAK-1 live repro helper — run inside WSL2 Ubuntu on the NATIVE docker engine.
#   bash /mnt/c/dev/aindy-apps-monolith/scratchpad/memtxn_repro.sh <status|rebuild|probe>
#
# status  — what runtime version is the running API on, is the stack healthy
# rebuild — rebuild the api image so it picks up the new aindy-runtime floor, restart, wait healthy
# probe   — fire a login and sample pg_stat_activity mid-request (the xact_age_s == idle_s query)
set -uo pipefail

REPO="/mnt/c/dev/aindy-apps-monolith"
COMPOSE="docker-compose.prod.yml"
cd "$REPO"

dc() { docker compose -f "$COMPOSE" "$@"; }
api_cid() { dc ps -q api; }
pg_cid() { dc ps -q postgres; }

# The fingerprint query. xact_age_s == idle_s on every row is the leak signature:
# the connection opened a transaction, ran ONE memory_nodes SELECT, then sat
# idle-in-transaction for the whole life of that transaction.
read -r -d '' PGQ <<'SQL'
SELECT count(*)                                              AS count,
       state,
       wait_event_type,
       round(EXTRACT(epoch FROM (now() - xact_start))::numeric, 1)  AS xact_age_s,
       round(EXTRACT(epoch FROM (now() - state_change))::numeric, 1) AS idle_s,
       left(regexp_replace(query, '\s+', ' ', 'g'), 60)      AS query
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
GROUP BY state, wait_event_type, xact_age_s, idle_s, query
ORDER BY xact_age_s DESC NULLS LAST
LIMIT 25;
SQL

# Just the headline number: how many connections are idle-in-transaction on memory_nodes.
read -r -d '' PGQ_SUMMARY <<'SQL'
SELECT count(*) FILTER (WHERE state = 'idle in transaction')                        AS idle_in_txn,
       count(*) FILTER (WHERE state = 'idle in transaction'
                          AND query ILIKE '%memory_nodes%')                          AS idle_in_txn_memory,
       count(*)                                                                      AS total_conns,
       coalesce(round(max(EXTRACT(epoch FROM (now() - xact_start)))::numeric, 1), 0)  AS oldest_xact_s
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid();
SQL

psql_run() { docker exec -i "$(pg_cid)" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c "$1"; }

case "${1:-status}" in

status)
  echo "==> engine"
  docker info --format '    name={{.Name}} server={{.ServerVersion}}'
  echo "==> containers"
  dc ps --format '    {{.Service}}\t{{.Status}}'
  echo "==> runtime version inside the api container"
  docker exec "$(api_cid)" python -c 'import importlib.metadata as m; print("    aindy-runtime==" + m.version("aindy-runtime"))'
  echo "==> /api/version runtime block"
  docker exec "$(api_cid)" python - <<'PY'
import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/version"))
r = d.get("runtime", {})
for k in ("boot_profile", "app_plugins_loaded", "app_plugin_count", "runtime_version"):
    if k in r:
        print(f"    {k}={r[k]}")
PY
  ;;

rebuild)
  echo "==> rebuilding api on the new runtime floor (no cache on the dep layer)"
  dc build --pull api || exit 1
  dc up -d api || exit 1
  echo "==> waiting for health"
  CID="$(api_cid)"
  for i in $(seq 1 45); do
    st="$(docker inspect --format '{{.State.Health.Status}}' "$CID" 2>/dev/null || echo '?')"
    echo "    t+$((i*4))s health=$st"
    [ "$st" = "healthy" ] && break
    sleep 4
  done
  docker exec "$CID" python -c 'import importlib.metadata as m; print("    now running aindy-runtime==" + m.version("aindy-runtime"))'
  ;;

probe)
  EMAIL="${REPRO_EMAIL:?set REPRO_EMAIL}"
  PASSWORD="${REPRO_PASSWORD:?set REPRO_PASSWORD}"
  echo "==> baseline (before login)"
  psql_run "$PGQ_SUMMARY"

  echo "==> firing login in background, sampling pg_stat_activity mid-request"
  START=$(date +%s)
  ( docker exec "$(api_cid)" python - "$EMAIL" "$PASSWORD" <<'PY' > /tmp/login_result.txt 2>&1
import json, sys, time, urllib.request, urllib.error
email, password = sys.argv[1], sys.argv[2]
body = json.dumps({"email": email, "password": password}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/auth/login", data=body,
                             headers={"Content-Type": "application/json"})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        print(f"status={r.status} elapsed={time.time()-t0:.1f}s")
except urllib.error.HTTPError as e:
    print(f"status={e.code} elapsed={time.time()-t0:.1f}s body={e.read()[:200]!r}")
except Exception as e:
    print(f"ERROR after {time.time()-t0:.1f}s: {e!r}")
PY
  ) &
  LOGIN_PID=$!

  # Sample every 2s while the login is in flight.
  for i in $(seq 1 12); do
    sleep 2
    echo "---- t+$((i*2))s ----"
    psql_run "$PGQ_SUMMARY"
    kill -0 $LOGIN_PID 2>/dev/null || { echo "    (login finished)"; break; }
  done

  wait $LOGIN_PID 2>/dev/null
  echo "==> login result"
  cat /tmp/login_result.txt
  echo "==> total wall clock: $(( $(date +%s) - START ))s"
  echo "==> full fingerprint table (post-request)"
  psql_run "$PGQ"
  ;;

query)
  # Just print the query so it can be pasted anywhere.
  echo "$PGQ"
  ;;

*)
  echo "usage: $0 <status|rebuild|probe|query>"; exit 2 ;;
esac
