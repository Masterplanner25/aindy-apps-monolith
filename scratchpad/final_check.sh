#!/usr/bin/env bash
echo "=== api container state ==="
docker inspect aindy-apps-monolith-api-1 --format 'Health={{.State.Health.Status}} Started={{.State.StartedAt}} Restarts={{.RestartCount}}' 2>/dev/null
echo "=== internal serve (is the api actually up?) ==="
docker exec aindy-apps-monolith-api-1 python -c "import urllib.request as u;print('internal /health ->',u.urlopen('http://127.0.0.1:8000/health',timeout=5).status)" 2>/dev/null || echo "  internal ERR (api booting/down)"
echo "=== WSL-side host port bound? ==="
ss -tlnp 2>/dev/null | grep ':8000' | head -1 || echo "  no 8000 listener"
