#!/usr/bin/env bash
echo "=== waiting for api to fully boot and hold healthy (untouched) ==="
for i in $(seq 1 30); do
  st=$(docker inspect --format '{{.State.Health.Status}}' aindy-apps-monolith-api-1 2>/dev/null || echo '?')
  echo "  t+$((i*5))s health=$st"
  [ "$st" = "healthy" ] && { hc=$((${hc:-0}+1)); } || hc=0
  [ "${hc:-0}" -ge 4 ] && { echo "  >>> held healthy 4 checks (20s) — settled"; break; }
  sleep 5
done
echo "=== internal serve check ==="
docker exec aindy-apps-monolith-api-1 python -c "import urllib.request as u;print('internal /health ->',u.urlopen('http://127.0.0.1:8000/health',timeout=5).status)" 2>/dev/null || echo "  internal ERR"
