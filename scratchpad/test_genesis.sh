#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"gen+{stamp}@local.test", f"GenPass!{stamp}"
def req(method, path, tok=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = f"Bearer {tok}"
    r = urllib.request.Request("http://127.0.0.1:8000"+path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=90) as x: return x.status, x.read()
    except urllib.error.HTTPError as e: return e.code, e.read()
    except Exception as e: return None, repr(e).encode()

req("POST","/auth/register",body={"email":email,"password":password,"username":f"gen{stamp}"})
_, b = req("POST","/auth/login",body={"email":email,"password":password})
tok = json.loads(b).get("access_token","")
print(f"  token={'ok' if tok else 'NONE'}\n")

for method, path, body in [
    ("POST", "/apps/genesis/session", {}),
    ("POST", "/apps/genesis/session", None),
    ("POST", "/genesis/session", {}),
]:
    s, r = req(method, path, tok, body)
    print(f"  {method} {path:<28} body={'{}' if body is not None else 'none':<5} -> {s}  {r[:220]}")
PY
echo
echo "=== api log for genesis ==="
docker logs "$API" --since 60s 2>&1 | grep -iE "genesis" | tail -10
