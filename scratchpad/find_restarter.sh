#!/usr/bin/env bash
echo "=== docker events last 5 min (who is stopping/starting containers?) ==="
timeout 4 docker events --since 5m --until now --filter 'type=container' --format '{{.Time}} {{.Action}} {{.Actor.Attributes.name}}' 2>/dev/null | grep -E "aindy|mongo" | tail -25 || echo "(none)"
echo
echo "=== any docker compose / rebuild processes running in WSL? ==="
ps aux 2>/dev/null | grep -iE "docker compose|docker-compose|rebuild|compose up" | grep -v grep | head
echo
echo "=== systemd/docker daemon restarts? ==="
systemctl is-active docker 2>/dev/null || service docker status 2>/dev/null | head -2
echo "=== dmesg OOM kills? ==="
dmesg 2>/dev/null | grep -iE "oom|killed process|out of memory" | tail -5 || echo "(no dmesg access)"
