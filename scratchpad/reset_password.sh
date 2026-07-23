#!/usr/bin/env bash
# Reset ONE account's password using the runtime's own hash_password (guaranteed compatible),
# then prove it by logging in. Scoped to a single email; refuses if it doesn't match exactly one row.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
TARGET_EMAIL="shawnknight@the-master-plan.com"

docker exec -i -e TARGET_EMAIL="$TARGET_EMAIL" "$API" python - <<'PY'
import os, secrets, string, json, urllib.request, urllib.error
from AINDY.db.database import SessionLocal
from AINDY.db.models.user import User
from AINDY.services.auth_service import hash_password, verify_password

email = os.environ["TARGET_EMAIL"]

# Strong random password: 20 chars, guaranteed mix, URL/JSON-safe (no quotes/backslashes).
alphabet = string.ascii_letters + string.digits + "!@#%^*-_=+"
while True:
    pw = "".join(secrets.choice(alphabet) for _ in range(20))
    if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw) and any(c in "!@#%^*-_=+" for c in pw)):
        break

db = SessionLocal()
try:
    rows = db.query(User).filter(User.email == email).all()
    if len(rows) != 1:
        print(f"ABORT: expected exactly 1 account for {email}, found {len(rows)}")
        raise SystemExit(1)
    user = rows[0]
    user.hashed_password = hash_password(pw)
    db.commit()
    # sanity: the stored hash verifies against the new password
    db.refresh(user)
    assert verify_password(pw, user.hashed_password), "verify_password failed after reset"
    print(f"  reset OK for {email} (user_id={user.id})")
finally:
    db.close()

# prove it end-to-end through the real login endpoint
req = urllib.request.Request("http://127.0.0.1:8000/auth/login",
                             data=json.dumps({"email": email, "password": pw}).encode(),
                             headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        ok = r.status == 200 and bool(json.loads(r.read()).get("access_token"))
        print(f"  login check -> {r.status} (token: {'yes' if ok else 'NO'})")
except urllib.error.HTTPError as e:
    print(f"  login check -> {e.code} FAILED")
    raise SystemExit(1)

print("\n==================== NEW PASSWORD ====================")
print(f"  email    : {email}")
print(f"  password : {pw}")
print("=====================================================")
PY
