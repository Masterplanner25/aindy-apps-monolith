"""
Freelance domain smoke test.

Tests the Stripe-free HTTP surface of /apps/freelance/* only.
Skips: POST /refund/{id}, POST /subscription/{id}/cancel, POST /webhook/stripe
       POST /generate/{id} (LLM-backed delivery generation).

Response adapter: NONE registered for "freelance" prefix.
  _execute_freelance uses return_result=True and manually injects execution_envelope.
  HTTP body = handler return value + {"execution_envelope": {...}} merged at top level.
  There is no canonical data/status wrapper.

Flow engine behavior: single-node flows return the VALUE of the output_patch key
  as `result.data`, not {key: value}. So the actual HTTP body shapes are:

  POST /order (201)        body = {**order_fields, "execution_envelope": {...}}  → body["id"]
  GET  /orders             body = {"status": "SUCCESS", "orders": [...], "execution_envelope": {...}}
  POST /deliver/{id}       body = {**order_fields, "execution_envelope": {...}}  → body["delivery_status"]
  PUT  /delivery/{id}      body = {**order_fields, "execution_envelope": {...}}  → body["delivery_type"]
  POST /feedback           body = {**feedback_fields, "execution_envelope": {...}}
  GET  /feedback           body = [...] (bare list — list results skip envelope injection)
  POST /metrics/update     body = {**metrics_fields, "execution_envelope": {...}}
  GET  /metrics/latest     404 for fresh user; 200 once update has run

Usage:
  python scripts/smoke_freelance.py
  python scripts/smoke_freelance.py --base-url http://localhost:8000
"""

import argparse
import sys
import uuid

try:
    import requests
except ImportError:
    print("FATAL: 'requests' not installed. Run: pip install requests")
    sys.exit(1)

BASE = "/apps/freelance"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(label: str, detail: str = "") -> None:
    print(f"  OK  {label}" + (f" -- {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"  FAIL {label}" + (f" -- {detail}" if detail else ""))


def _get(session, base, path, label, expect=(200,)):
    r = session.get(f"{base}{path}")
    if r.status_code not in expect:
        _fail(label, f"GET {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


def _post(session, base, path, body, label, expect=(200, 201), headers=None):
    r = session.post(f"{base}{path}", json=body, headers=headers or {})
    if r.status_code not in expect:
        _fail(label, f"POST {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


def _put(session, base, path, body, label, expect=(200,)):
    r = session.put(f"{base}{path}", json=body)
    if r.status_code not in expect:
        _fail(label, f"PUT {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def step_health(session, base, results):
    body, ok = _get(session, base, "/health", "health check")
    if ok:
        _ok("health check", f"status={body.get('status')}")
    results["health"] = "PASS" if ok else "FAIL"


def step_auth(session, base, results):
    email = f"smoke-fl-{uuid.uuid4().hex[:8]}@aindy.local"
    pw = "SmokeTest1!"

    _, ok = _post(session, base, "/auth/register", {"email": email, "password": pw}, "register")
    if not ok:
        results["auth"] = "FAIL"
        return None

    body, ok = _post(session, base, "/auth/login", {"email": email, "password": pw}, "login")
    if not ok:
        results["auth"] = "FAIL"
        return None

    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    if not token:
        _fail("login", f"no access_token in: {body}")
        results["auth"] = "FAIL"
        return None

    session.headers["Authorization"] = f"Bearer {token}"
    _ok("auth register + login", email)
    results["auth"] = "PASS"
    return token


def step_create_order(session, base, results):
    """POST /apps/freelance/order — requires Idempotency-Key header, status 201.
    Body = flat order fields + execution_envelope (flow engine returns output_patch value)."""
    idem_key = f"smoke-fl-order-{uuid.uuid4().hex}"
    payload = {
        "client_name": "Smoke Test Client",
        "client_email": "smoke@aindy.local",
        "service_type": "automation",
        "project_details": "Automated smoke test order",
        "price": 99.0,
        "delivery_type": "manual",
    }
    body, ok = _post(
        session, base, f"{BASE}/order", payload, "create order",
        expect=(200, 201),
        headers={"Idempotency-Key": idem_key},
    )
    if not ok:
        results["create_order"] = "FAIL"
        return None

    # body = {id, client_name, ..., execution_envelope} — flat order dict
    if not isinstance(body, dict):
        _fail("create order", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["create_order"] = "FAIL"
        return None

    order_id = body.get("id")
    if order_id is None:
        _fail("create order", f"no 'id' in body: {list(body.keys())}")
        results["create_order"] = "FAIL"
        return None

    _ok("create order", f"id={order_id}  client={body.get('client_name')!r}  status={body.get('status')!r}")
    results["create_order"] = "PASS"
    return order_id


def step_list_orders(session, base, results):
    """GET /apps/freelance/orders — body = {"status": ..., "orders": [...], "execution_envelope": {...}}."""
    body, ok = _get(session, base, f"{BASE}/orders", "list orders")
    if not ok:
        results["list_orders"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("list orders", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["list_orders"] = "FAIL"
        return

    if "orders" not in body:
        _fail("list orders", f"no 'orders' key in body: {list(body.keys())}")
        results["list_orders"] = "FAIL"
        return

    orders = body.get("orders") or []
    _ok("list orders", f"{len(orders)} order(s)")
    results["list_orders"] = "PASS"


def step_deliver_order(session, base, order_id, results):
    """POST /apps/freelance/deliver/{order_id} — body = flat order fields + execution_envelope."""
    body, ok = _post(session, base, f"{BASE}/deliver/{order_id}", None, "deliver order")
    if not ok:
        results["deliver_order"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("deliver order", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["deliver_order"] = "FAIL"
        return

    order_id_back = body.get("id")
    delivery_status = body.get("delivery_status")
    if order_id_back is None:
        _fail("deliver order", f"no 'id' in body: {list(body.keys())}")
        results["deliver_order"] = "FAIL"
        return

    _ok("deliver order", f"id={order_id_back}  delivery_status={delivery_status!r}")
    results["deliver_order"] = "PASS"


def step_update_delivery(session, base, order_id, results):
    """PUT /apps/freelance/delivery/{order_id} — body = flat order fields + execution_envelope."""
    payload = {
        "delivery_type": "email",
        "delivery_config": {"recipient": "smoke@aindy.local"},
    }
    body, ok = _put(session, base, f"{BASE}/delivery/{order_id}", payload, "update delivery config")
    if not ok:
        results["update_delivery"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("update delivery config", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["update_delivery"] = "FAIL"
        return

    delivery_type = body.get("delivery_type")
    _ok("update delivery config", f"id={order_id}  delivery_type={delivery_type!r}")
    results["update_delivery"] = "PASS"


def step_collect_feedback(session, base, order_id, results):
    """POST /apps/freelance/feedback — body = flat feedback fields + execution_envelope."""
    payload = {
        "order_id": order_id,
        "rating": 5,
        "feedback_text": "Excellent automated smoke test!",
    }
    body, ok = _post(session, base, f"{BASE}/feedback", payload, "collect feedback")
    if not ok:
        results["collect_feedback"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("collect feedback", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["collect_feedback"] = "FAIL"
        return

    fb_id = body.get("id")
    if fb_id is None:
        _fail("collect feedback", f"no 'id' in body: {list(body.keys())}")
        results["collect_feedback"] = "FAIL"
        return

    _ok("collect feedback", f"feedback_id={fb_id}  order_id={order_id}  rating={payload['rating']}")
    results["collect_feedback"] = "PASS"


def step_list_feedback(session, base, results):
    """GET /apps/freelance/feedback — body = bare list (no envelope; list skips dict injection)."""
    body, ok = _get(session, base, f"{BASE}/feedback", "list feedback")
    if not ok:
        results["list_feedback"] = "FAIL"
        return

    if not isinstance(body, list):
        _fail("list feedback", f"expected list, got {type(body).__name__}: {str(body)[:200]}")
        results["list_feedback"] = "FAIL"
        return

    _ok("list feedback", f"{len(body)} feedback item(s)")
    results["list_feedback"] = "PASS"


def step_update_metrics(session, base, results):
    """POST /apps/freelance/metrics/update — body = flat metrics fields + execution_envelope."""
    body, ok = _post(session, base, f"{BASE}/metrics/update", None, "update metrics")
    if not ok:
        results["update_metrics"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("update metrics", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["update_metrics"] = "FAIL"
        return

    has_revenue = "total_revenue" in body or "id" in body
    if not has_revenue:
        _fail("update metrics", f"no metrics fields in body: {list(body.keys())}")
        results["update_metrics"] = "FAIL"
        return

    _ok("update metrics", f"id={body.get('id')}  total_revenue={body.get('total_revenue')}")
    results["update_metrics"] = "PASS"


def step_get_metrics_latest(session, base, results):
    """GET /apps/freelance/metrics/latest — 200 after update ran, 404 for fresh user."""
    body, ok = _get(session, base, f"{BASE}/metrics/latest", "metrics latest", expect=(200, 404))
    if not ok:
        results["metrics_latest"] = "FAIL"
        return

    if body is None:
        _ok("metrics latest", "404 — no metrics (acceptable for fresh user)")
        results["metrics_latest"] = "PASS"
        return

    if not isinstance(body, dict):
        _fail("metrics latest", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["metrics_latest"] = "FAIL"
        return

    _ok("metrics latest", f"id={body.get('id')}  total_revenue={body.get('total_revenue')}")
    results["metrics_latest"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Freelance domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("FREELANCE DOMAIN SMOKE TEST")
    print(f"Target: {base}")
    print("Skipping: /refund, /subscription/cancel, /webhook/stripe, /generate (Stripe/LLM)")
    print("=" * 60)

    session = requests.Session()
    session.headers["Content-Type"] = "application/json"
    results = {}

    print("\n[1] Health")
    step_health(session, base, results)

    print("\n[2] Auth")
    token = step_auth(session, base, results)
    if not token:
        print("\nAuth failed — cannot continue.")
        _print_summary(results)
        sys.exit(1)

    print("\n[3] Create order (POST /apps/freelance/order)")
    order_id = step_create_order(session, base, results)

    print("\n[4] List orders (GET /apps/freelance/orders)")
    step_list_orders(session, base, results)

    print("\n[5] Deliver order (POST /apps/freelance/deliver/{id})")
    if order_id is not None:
        step_deliver_order(session, base, order_id, results)
    else:
        results["deliver_order"] = "SKIP"

    print("\n[6] Update delivery config (PUT /apps/freelance/delivery/{id})")
    if order_id is not None:
        step_update_delivery(session, base, order_id, results)
    else:
        results["update_delivery"] = "SKIP"

    print("\n[7] Collect feedback (POST /apps/freelance/feedback)")
    if order_id is not None:
        step_collect_feedback(session, base, order_id, results)
    else:
        results["collect_feedback"] = "SKIP"

    print("\n[8] List feedback (GET /apps/freelance/feedback)")
    step_list_feedback(session, base, results)

    print("\n[9] Update metrics (POST /apps/freelance/metrics/update)")
    step_update_metrics(session, base, results)

    print("\n[10] Latest metrics (GET /apps/freelance/metrics/latest)")
    step_get_metrics_latest(session, base, results)

    _print_summary(results)

    failed = [k for k, v in results.items() if v == "FAIL"]
    sys.exit(1 if failed else 0)


def _print_summary(results):
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    icons = {"PASS": "OK", "FAIL": "FAIL", "SKIP": "--"}
    for name, result in results.items():
        icon = icons.get(result, "??")
        print(f"  {icon}  {name}: {result}")
    print()
    failed = [k for k, v in results.items() if v == "FAIL"]
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    else:
        print("ALL TESTS PASSED -- freelance domain smoke OK")


if __name__ == "__main__":
    main()
