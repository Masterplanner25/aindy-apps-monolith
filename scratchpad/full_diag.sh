#!/usr/bin/env bash
echo "=== container state (same instance or recreated?) ==="
docker inspect aindy-apps-monolith-api-1 --format 'Started={{.State.StartedAt}} Health={{.State.Health.Status}} Restarts={{.RestartCount}} Status={{.State.Status}}' 2>/dev/null
echo "=== is something running docker compose up in a loop? (recent docker events) ==="
timeout 3 docker events --since 3m --until now --filter 'container=aindy-apps-monolith-api-1' 2>/dev/null | tail -8 || echo "(no events / timed out)"
echo "=== recent 500 traceback in api logs ==="
docker logs aindy-apps-monolith-api-1 --since 3m 2>&1 | grep -iE "Traceback|Error|Exception|500|mongo|ServerSelection|pymongo" | grep -viE "INFO|Bootstrap|STRIPE|ordering gap" | tail -15
