#!/usr/bin/env bash
echo "=== containers after reboot ==="
docker ps --format '{{.Names}}: {{.Status}}' 2>/dev/null | grep aindy || echo "  (stack not up — needs 'docker compose ... up -d')"
echo "=== wait for api healthy (untouched) ==="
for i in $(seq 1 30); do
  st=$(docker inspect --format '{{.State.Health.Status}}' aindy-apps-monolith-api-1 2>/dev/null || echo '?')
  echo "  t+$((i*5))s health=$st"
  [ "$st" = "healthy" ] && break
  sleep 5
done
