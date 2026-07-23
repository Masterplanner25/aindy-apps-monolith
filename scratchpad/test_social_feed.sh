#!/usr/bin/env bash
# Create a post, then fetch the feed. Is the just-created post returned?
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"soc+{stamp}@local.test",f"SocPass!{stamp}"
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
call("POST","/auth/register",body={"email":email,"password":password,"username":f"soc{stamp}"})
_,d=call("POST","/auth/login",body={"email":email,"password":password})
tok=d["access_token"]

s,post=call("POST","/apps/social/post",tok,{"content":"Hello from the walkthrough test post!","visibility":"public"})
print(f"  POST /apps/social/post -> {s}")
print(f"    keys={sorted(post.keys()) if isinstance(post,dict) else post}")
pid = post.get("id") or (post.get("post") or {}).get("id") or (post.get("data") or {}).get("id")
print(f"    created post id={pid}  visibility={post.get('visibility')}  status={post.get('status')}  trust={post.get('trust_score') or post.get('author_trust')}")

time.sleep(1)
s,feed=call("GET","/apps/social/feed?limit=20",tok)
items = feed.get("items") or feed.get("feed") or feed.get("posts") or (feed if isinstance(feed,list) else [])
if isinstance(feed,dict) and "data" in feed and isinstance(feed["data"],(list,dict)):
    items = feed["data"] if isinstance(feed["data"],list) else feed["data"].get("items", items)
print(f"\n  GET /apps/social/feed -> {s}")
print(f"    feed keys={sorted(feed.keys()) if isinstance(feed,dict) else type(feed).__name__}")
print(f"    feed item count={len(items) if isinstance(items,list) else '?'}")
if isinstance(items,list):
    found = any((it.get('post',{}).get('id')==pid or it.get('id')==pid) for it in items if isinstance(it,dict))
    print(f"    our post present in feed? {found}")
    if items:
        print(f"    first item shape: {json.dumps(items[0])[:200]}")
PY
