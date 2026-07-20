#!/usr/bin/env bash
# RT-MEMTXN-LEAK-1 final verification on the REAL aindy-runtime 1.10.2 wheel.
#
# The 1.10.1 probe had an ambiguity: "request too fast to sample" and "recall never ran"
# produce identical output (0 observed memory_nodes queries). A fast login is therefore NOT
# by itself evidence of a fix. This resolves it with an independent, sampling-free counter:
#
#   pg_stat_user_tables tracks cumulative scans per table. The BEFORE/AFTER delta on
#   memory_nodes proves the recall actually executed, no matter how brief the request.
#
# So the two questions are answered separately:
#   did recall run?      -> scan-count delta > 0        (correctness / validity)
#   did it leak?         -> peak idle-in-transaction     (the bug itself)
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"; PG="$(dc ps -q postgres)"
PSQL() { docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -tAc "$1"; }

scans() {  # cumulative scans + rows read on memory_nodes
  PSQL "SELECT coalesce(seq_scan,0)+coalesce(idx_scan,0) || ' ' || coalesce(seq_tup_read,0)+coalesce(idx_tup_fetch,0)
          FROM pg_stat_user_tables WHERE relname='memory_nodes';"
}

STAMP="$(date +%s)"
EMAIL="v1102+${STAMP}@local.test"; PASSWORD="VerifyPass!${STAMP}"

echo "=== RT-MEMTXN-LEAK-1 verification on $(docker exec "$API" python -c 'import importlib.metadata as m;print("aindy-runtime==" + m.version("aindy-runtime"))') ==="
echo

echo "--- registering repro account ---"
docker exec -i "$API" python - "$EMAIL" "$PASSWORD" <<'PY'
import json, sys, time, urllib.request, urllib.error
email, password = sys.argv[1], sys.argv[2]
body = json.dumps({"email": email, "password": password, "username": email.split("@")[0]}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/auth/register", data=body,
                             headers={"Content-Type": "application/json"})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        print(f"    /auth/register -> {r.status} in {time.time()-t0:.2f}s")
except urllib.error.HTTPError as e:
    print(f"    /auth/register -> {e.code} in {time.time()-t0:.2f}s :: {e.read()[:160]!r}")
except Exception as e:
    print(f"    /auth/register -> ERROR after {time.time()-t0:.2f}s :: {e!r}")
PY
echo

read -r S0 R0 <<< "$(scans)"
echo "--- memory_nodes scan counter BEFORE login: scans=$S0 rows_read=$R0 ---"
echo

echo "--- firing LOGIN, sampling every 100ms ---"
docker exec -i "$API" python - "$EMAIL" "$PASSWORD" > /tmp/v1102_login.txt 2>&1 <<'PY' &
import json, sys, time, urllib.request, urllib.error
email, password = sys.argv[1], sys.argv[2]
body = json.dumps({"email": email, "password": password}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/auth/login", data=body,
                             headers={"Content-Type": "application/json"})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        print(f"LOGIN status={r.status} elapsed={time.time()-t0:.2f}s")
except urllib.error.HTTPError as e:
    print(f"LOGIN status={e.code} elapsed={time.time()-t0:.2f}s body={e.read()[:160]!r}")
except Exception as e:
    print(f"LOGIN ERROR after {time.time()-t0:.2f}s: {e!r}")
PY
LOGIN_PID=$!

PEAK_IDLE=0; PEAK_MEM=0; SAMPLES=0
while kill -0 $LOGIN_PID 2>/dev/null; do
  ROW="$(PSQL "SELECT count(*) FILTER (WHERE state='idle in transaction')
                    || ' ' || count(*) FILTER (WHERE state='idle in transaction' AND query ILIKE '%memory_nodes%')
               FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid();" 2>/dev/null)"
  set -- $ROW; I="${1:-0}"; M="${2:-0}"
  [ "${I:-0}" -gt "$PEAK_IDLE" ] 2>/dev/null && PEAK_IDLE=$I
  [ "${M:-0}" -gt "$PEAK_MEM" ] 2>/dev/null && PEAK_MEM=$M
  SAMPLES=$((SAMPLES+1))
  sleep 0.1
done
wait $LOGIN_PID 2>/dev/null

sleep 1   # let the stats collector settle
read -r S1 R1 <<< "$(scans)"

echo
echo "================= RESULT ================="
cat /tmp/v1102_login.txt
echo
echo "  DID RECALL RUN?  (independent of sampling)"
echo "    memory_nodes scans  : $S0 -> $S1   (delta $((S1-S0)))"
echo "    rows read           : $R0 -> $R1   (delta $((R1-R0)))"
if [ "$((S1-S0))" -gt 0 ]; then
  echo "    => YES, the recall read path executed. A low concurrency number below is a REAL pass."
else
  echo "    => NO SCANS. The recall did NOT run — a fast login here proves nothing."
fi
echo
echo "  DID IT LEAK?"
echo "    samples taken during request : $SAMPLES (every ~100ms)"
echo "    peak idle_in_transaction     : $PEAK_IDLE"
echo "    peak on memory_nodes         : $PEAK_MEM"
echo "    (was 60 / 60 on 1.10.1, login 41.9s)"
echo "=========================================="
