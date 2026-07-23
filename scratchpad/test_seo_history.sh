#!/usr/bin/env bash
# Does an SEO analyze actually produce a retrievable "seo_analysis" history row?
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"; PG="$(dc ps -q postgres)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"seo+{stamp}@local.test",f"SeoPass!{stamp}"
BASE="http://127.0.0.1:8000"
def call(m,p,tok=None,body=None):
    d=json.dumps(body).encode() if body is not None else None
    h={"Content-Type":"application/json"}
    if tok:h["Authorization"]=f"Bearer {tok}"
    r=urllib.request.Request(BASE+p,data=d,headers=h,method=m)
    try:
        with urllib.request.urlopen(r,timeout=90) as x:return x.status,json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:return e.code,json.loads(e.read())
        except Exception:return e.code,{}
call("POST","/auth/register",body={"email":email,"password":password,"username":f"s{stamp}"})
_,d=call("POST","/auth/login",body={"email":email,"password":password})
tok=d["access_token"]
open("/tmp/seo_email.txt","w").write(email)

article="Search engine optimization improves content visibility. Keyword density and readability both matter for ranking. This article explains SEO best practices for content writers."
s,res=call("POST","/apps/seo/analyze",tok,{"text":article,"top_n":5})
print(f"  POST /apps/seo/analyze -> {s}  keys={sorted(res.keys()) if isinstance(res,dict) else res}")

# now read history the way the frontend panel does
for path in ("/apps/search/history?search_type=seo_analysis&limit=25",
             "/apps/search/history?limit=25"):
    s,h=call("GET",path,tok)
    items = h.get("history") or h.get("items") or h.get("data") or (h if isinstance(h,list) else [])
    if isinstance(items, dict): items = items.get("history") or items.get("items") or []
    print(f"  GET {path[:48]:48} -> {s}  count={len(items) if isinstance(items,list) else '?'}  keys={sorted(h.keys()) if isinstance(h,dict) else type(h).__name__}")
    if isinstance(items,list) and items:
        print(f"      first item search_type={items[0].get('search_type')!r} query={str(items[0].get('query'))[:40]!r}")
PY

EMAIL="$(docker exec -i "$API" cat /tmp/seo_email.txt 2>/dev/null)"
echo
echo "  === raw search_history rows for that user in the DB ==="
docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
"SELECT search_type, count(*) FROM search_history
   WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL') GROUP BY 1;" 2>/dev/null \
 || docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
"SELECT column_name FROM information_schema.columns WHERE table_name='search_history' ORDER BY ordinal_position;"
