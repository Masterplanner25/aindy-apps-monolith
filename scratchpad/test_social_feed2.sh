#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"soc2+{stamp}@local.test",f"Soc2Pass!{stamp}"
BASE="http://127.0.0.1:8000"
def call(m,p,tok=None,body=None):
    d=json.dumps(body).encode() if body is not None else None
    h={"Content-Type":"application/json"}
    if tok:h["Authorization"]=f"Bearer {tok}"
    r=urllib.request.Request(BASE+p,data=d,headers=h,method=m)
    try:
        with urllib.request.urlopen(r,timeout=60) as x:return x.status,json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:return e.code,json.loads(e.read())
        except Exception:return e.code,{}
call("POST","/auth/register",body={"email":email,"password":password,"username":f"soc2{stamp}"})
_,d=call("POST","/auth/login",body={"email":email,"password":password})
tok=d["access_token"]

# exact frontend body shape
body={"author_id":"me","author_username":"me","content":"Walkthrough test post","trust_tier_required":"observer","tags":[]}
s,post=call("POST","/apps/social/post",tok,body)
print(f"  POST /apps/social/post -> {s}")
if s not in (200,201):
    print(f"    {json.dumps(post)[:300]}")
else:
    print(f"    keys={sorted(post.keys())}")
    for k in ("id","author_id","author_username","visibility","status","trust_tier_required","trust_tier"):
        if k in post: print(f"      {k}={post[k]}")
    pid=post.get("id")

    time.sleep(1)
    s2,feed=call("GET","/apps/social/feed?limit=20",tok)
    data = feed.get("data") if isinstance(feed,dict) else feed
    items = (data.get("items") or data.get("feed") or data.get("posts") if isinstance(data,dict) else data) or []
    if isinstance(feed,dict) and isinstance(feed.get("data"),list): items=feed["data"]
    print(f"\n  GET /apps/social/feed -> {s2}  items={len(items) if isinstance(items,list) else '?'}")
    if isinstance(items,list):
        ids=[ (it.get('post',{}) or {}).get('id') or it.get('id') for it in items if isinstance(it,dict)]
        print(f"    our post id={pid} present? {pid in ids}")
        if items: print(f"    first item: {json.dumps(items[0])[:220]}")

    # also: does the author see their OWN posts via a profile/posts endpoint?
    s3,mine=call("GET","/apps/social/profile",tok)
    print(f"\n  GET /apps/social/profile -> {s3}  keys={sorted(mine.keys()) if isinstance(mine,dict) else mine}")
PY
