#!/usr/bin/env bash
# Follow-up: login on 1.10.2 is fast AND does zero memory_nodes scans. Distinguish
#   (a) recall moved off the login path / went async  -> fine
#   (b) recall silently no-ops everywhere             -> functional regression behind a perf win
# by (1) watching the counter for 30s after login (catches async) and
#    (2) hitting an endpoint that provably reads memory_nodes, with a real token.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"; PG="$(dc ps -q postgres)"
PSQL() { docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -tAc "$1"; }
scans() { PSQL "SELECT coalesce(seq_scan,0)+coalesce(idx_scan,0) FROM pg_stat_user_tables WHERE relname='memory_nodes';"; }

STAMP="$(date +%s)"
EMAIL="recall+${STAMP}@local.test"; PASSWORD="RecallPass!${STAMP}"

echo "=== recall-reality check on $(docker exec "$API" python -c 'import importlib.metadata as m;print(m.version("aindy-runtime"))') ==="

TOKEN="$(docker exec -i "$API" python - "$EMAIL" "$PASSWORD" <<'PY'
import json, sys, urllib.request, urllib.error
email, password = sys.argv[1], sys.argv[2]
def post(path, payload):
    req = urllib.request.Request("http://127.0.0.1:8000"+path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except Exception:
        return {}
post("/auth/register", {"email": email, "password": password, "username": email.split("@")[0]})
d = post("/auth/login", {"email": email, "password": password})
print(d.get("access_token") or d.get("token") or "")
PY
)"
echo "token acquired: $([ -n "$TOKEN" ] && echo yes || echo NO)"

S_LOGIN="$(scans)"
echo "scans right after login: $S_LOGIN"
echo "--- watching 30s for ASYNC/background recall ---"
for i in 1 2 3 4 5 6; do
  sleep 5
  echo "    t+$((i*5))s scans=$(scans)"
done
S_AFTER="$(scans)"
echo "delta over 30s post-login: $((S_AFTER-S_LOGIN))"
echo

echo "--- now hit a memory-reading endpoint directly ---"
S_PRE="$(scans)"
docker exec -i "$API" python - "$TOKEN" <<'PY'
import json, sys, time, urllib.request, urllib.error
token = sys.argv[1]
for path in ("/api/memory/metrics", "/api/memory/traces"):
    req = urllib.request.Request("http://127.0.0.1:8000"+path,
                                 headers={"Authorization": f"Bearer {token}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            print(f"    {path} -> {r.status} in {time.time()-t0:.2f}s")
    except urllib.error.HTTPError as e:
        print(f"    {path} -> {e.code} in {time.time()-t0:.2f}s :: {e.read()[:120]!r}")
    except Exception as e:
        print(f"    {path} -> ERROR {e!r}")
PY
sleep 1
S_POST="$(scans)"
echo
echo "=================== VERDICT ==================="
echo "  memory_nodes scans during login window : $((S_AFTER-S_LOGIN))"
echo "  memory_nodes scans on memory endpoints : $((S_POST-S_PRE))"
if [ "$((S_POST-S_PRE))" -gt 0 ]; then
  echo "  => recall CAN read memory_nodes; login simply no longer does it inline. Healthy."
else
  echo "  => memory_nodes never read at all — investigate before calling this fixed."
fi
echo "==============================================="
