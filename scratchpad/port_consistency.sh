#!/usr/bin/env bash
echo "=== api stable? ==="
docker inspect aindy-apps-monolith-api-1 --format 'Health={{.State.Health.Status}} Started={{.State.StartedAt}} Restarts={{.RestartCount}}' 2>/dev/null
echo "=== internal api reachable consistently? (5 tries from inside WSL) ==="
for i in 1 2 3 4 5; do
  code=$(docker exec aindy-apps-monolith-api-1 python -c "import urllib.request as u;print(u.urlopen('http://127.0.0.1:8000/health',timeout=5).status)" 2>/dev/null || echo ERR)
  echo "  try $i: internal /health -> $code"
done
echo "=== .wslconfig networking mode? ==="
cat /mnt/c/Users/*/.wslconfig 2>/dev/null | grep -iE "networkingMode|localhostForwarding" || echo "(no .wslconfig networking settings — default NAT)"
