#!/usr/bin/env bash
echo "=== api restart count + exit reason ==="
docker inspect aindy-apps-monolith-api-1 --format 'RestartCount={{.RestartCount}} OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}} Status={{.State.Status}} Error={{.State.Error}}' 2>/dev/null
echo "=== last api log lines (crash reason) ==="
docker logs aindy-apps-monolith-api-1 --tail 25 2>&1 | grep -vE "INFO -|Bootstrap OK|request_complete" | tail -20
echo "=== memory pressure? ==="
free -h 2>/dev/null | head -2
echo "=== docker stats snapshot ==="
docker stats --no-stream --format '{{.Name}}: mem={{.MemUsage}} cpu={{.CPUPerc}}' 2>/dev/null | grep aindy
