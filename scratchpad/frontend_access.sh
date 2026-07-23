#!/usr/bin/env bash
# What URL does the user open, and does the SPA actually serve?
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
CID="$(dc ps -q api)"

echo "########## exposed ports ##########"
dc ps --format '  {{.Service}}\t{{.Ports}}'

echo
echo "########## is a built client bundled in the image? ##########"
docker exec "$CID" sh -c 'ls -la /app/client/dist 2>/dev/null | head -5 || echo "  no /app/client/dist"'
docker exec "$CID" sh -c 'ls /app/static 2>/dev/null | head -5 || echo "  no /app/static"'

echo
echo "########## does / return the SPA shell? ##########"
docker exec -i "$CID" python - <<'PY' 2>/dev/null
import urllib.request, urllib.error
for path in ("/", "/login", "/dashboard", "/assistant"):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000"+path, timeout=20) as r:
            body = r.read()
            is_html = b"<html" in body[:600].lower() or b"<!doctype" in body[:200].lower()
            print(f"  {path:<12} -> {r.status}  {len(body)} bytes  html={is_html}")
    except urllib.error.HTTPError as e:
        print(f"  {path:<12} -> {e.code}  {e.read()[:80]}")
    except Exception as e:
        print(f"  {path:<12} -> ERR {e!r}")
PY

echo
echo "########## reachable from Windows host? ##########"
echo "  WSL IP: $(hostname -I | awk '{print $1}')"
