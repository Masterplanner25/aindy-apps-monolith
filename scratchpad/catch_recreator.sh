#!/usr/bin/env bash
echo "=== docker events for the api container, 75s (catch create/destroy/die/kill) ==="
timeout 75 docker events --filter 'container=aindy-apps-monolith-api-1' --format '{{.Time}} {{.Action}} exitCode={{.Actor.Attributes.exitCode}}' 2>/dev/null &
EV=$!
# also sample started-at every 15s
for i in 1 2 3 4 5; do
  s=$(docker inspect --format '{{.State.StartedAt}}' aindy-apps-monolith-api-1 2>/dev/null)
  echo "  [sample $i] started=${s:11:8} health=$(docker inspect --format '{{.State.Health.Status}}' aindy-apps-monolith-api-1 2>/dev/null)"
  sleep 15
done
wait $EV 2>/dev/null
echo "=== any docker/compose processes running? ==="
ps -eo pid,etimes,cmd 2>/dev/null | grep -iE "compose|docker run|docker-compose" | grep -v grep | head
