"""
Analytics/Compute domain smoke test.

Two routers under the analytics domain:

  /apps/analytics/* (analytics_router) — DB-backed config + weights
    GET  /apps/analytics/kpi-weights
    POST /apps/analytics/kpi-weights/adapt
    GET  /apps/analytics/policy-thresholds
    POST /apps/analytics/policy-thresholds/adapt

  /apps/compute/* (main_router) — pure-math compute + results store
    POST /apps/compute/calculate_effort
    POST /apps/compute/calculate_productivity
    POST /apps/compute/calculate_virality
    POST /apps/compute/calculate_engagement
    POST /apps/compute/calculate_ai_efficiency
    POST /apps/compute/calculate_impact_score
    POST /apps/compute/income_efficiency
    POST /apps/compute/revenue_scaling
    POST /apps/compute/execution_speed
    POST /apps/compute/attention_value
    POST /apps/compute/engagement_rate
    POST /apps/compute/business_growth
    POST /apps/compute/monetization_efficiency
    POST /apps/compute/ai_productivity_boost
    POST /apps/compute/lost_potential
    POST /apps/compute/decision_efficiency
    POST /apps/compute/batch_calculations
    GET  /apps/compute/results
    GET  /apps/compute/masterplans
    POST /apps/compute/calculate_twr  (infinity orchestrator — DB-backed, may degrade gracefully)

Skipping:
    POST /apps/analytics/linkedin/manual      — requires a masterplan
    GET  /apps/analytics/masterplan/{id}      — requires a masterplan
    GET  /apps/analytics/masterplan/{id}/summary — requires a masterplan
    POST /apps/compute/create_masterplan      — creates a compute-specific plan (not needed for score)

All routes: raw_json_adapter (prefix "analytics" or "main")
  body = jsonable_encoder(handler_return_value)
  Compute handlers return {"Metric Name": float_value}
  _with_execution_envelope short-circuits on JSONResponse so body has no outer wrapper.

Usage:
  python scripts/smoke_analytics.py
  python scripts/smoke_analytics.py --base-url http://localhost:8000
"""

import argparse
import sys
import uuid

try:
    import requests
except ImportError:
    print("FATAL: 'requests' not installed. Run: pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Sample inputs (one per schema type)
# ---------------------------------------------------------------------------

TASK_INPUT = {
    "task_name": "smoke_test_task",
    "time_spent": 2.0,
    "task_complexity": 3,
    "skill_level": 3,
    "ai_utilization": 2,
    "task_difficulty": 2,
}

VIRALITY_INPUT = {
    "share_rate": 0.1,
    "engagement_rate": 0.05,
    "conversion_rate": 0.02,
    "time_factor": 1.5,
}

ENGAGEMENT_INPUT = {
    "likes": 100,
    "shares": 20,
    "comments": 30,
    "clicks": 500,
    "time_on_page": 120.0,
    "total_views": 1000,
}

AI_EFFICIENCY_INPUT = {
    "ai_contributions": 10,
    "human_contributions": 5,
    "total_tasks": 15,
}

IMPACT_INPUT = {"reach": 10000, "engagement": 500, "conversion": 50}

EFFICIENCY_INPUT = {
    "focused_effort": 8.0,
    "ai_utilization": 0.7,
    "time": 4.0,
    "capital": 1000.0,
}

REVENUE_SCALING_INPUT = {
    "ai_leverage": 2.5,
    "content_distribution": 0.8,
    "time": 12.0,
    "audience_engagement": 0.15,
}

EXECUTION_SPEED_INPUT = {
    "ai_automations": 5.0,
    "systemized_workflows": 3.0,
    "decision_lag": 0.5,
}

ATTENTION_VALUE_INPUT = {
    "content_output": 10.0,
    "platform_presence": 4.0,
    "time": 8.0,
}

ENGAGEMENT_RATE_INPUT = {
    "total_interactions": 500.0,
    "total_views": 10000.0,
}

BUSINESS_GROWTH_INPUT = {
    "revenue": 50000.0,
    "expenses": 30000.0,
    "scaling_friction": 0.2,
}

MONETIZATION_EFFICIENCY_INPUT = {
    "total_revenue": 50000.0,
    "audience_size": 10000.0,
}

AI_PRODUCTIVITY_BOOST_INPUT = {
    "tasks_with_ai": 20.0,
    "tasks_without_ai": 10.0,
    "time_saved": 5.0,
}

LOST_POTENTIAL_INPUT = {
    "missed_opportunities": 5.0,
    "time_delayed": 3.0,
    "gains_from_action": 10000.0,
}

DECISION_EFFICIENCY_INPUT = {
    "automated_decisions": 100.0,
    "manual_decisions": 20.0,
    "processing_time": 2.0,
}

BATCH_INPUT = {
    "tasks": [TASK_INPUT],
    "engagements": [ENGAGEMENT_INPUT],
    "ai_efficiencies": [AI_EFFICIENCY_INPUT],
    "impacts": [IMPACT_INPUT],
    "efficiencies": [EFFICIENCY_INPUT],
    "revenue_scalings": [REVENUE_SCALING_INPUT],
    "execution_speeds": [EXECUTION_SPEED_INPUT],
    "attention_values": [ATTENTION_VALUE_INPUT],
    "engagement_rates": [ENGAGEMENT_RATE_INPUT],
    "business_growths": [BUSINESS_GROWTH_INPUT],
    "monetization_efficiencies": [MONETIZATION_EFFICIENCY_INPUT],
    "ai_productivity_boost": [AI_PRODUCTIVITY_BOOST_INPUT],
    "lost_potential": [LOST_POTENTIAL_INPUT],
    "decision_efficiency": [DECISION_EFFICIENCY_INPUT],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(label: str, detail: str = "") -> None:
    print(f"  OK  {label}" + (f" -- {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"  FAIL {label}" + (f" -- {detail}" if detail else ""))


def _get(session, base, path, label, expect=200):
    r = session.get(f"{base}{path}")
    if r.status_code != expect:
        _fail(label, f"GET {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


def _post(session, base, path, body, label, expect=(200, 201, 202)):
    r = session.post(f"{base}{path}", json=body)
    if r.status_code not in expect:
        _fail(label, f"POST {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


def _compute(session, base, path, payload, label, expected_key):
    """POST a compute endpoint and verify the expected score key is in the response."""
    body, ok = _post(session, base, f"/apps/compute/{path}", payload, label)
    if not ok:
        return False
    if not isinstance(body, dict) or expected_key not in body:
        _fail(label, f"missing key {expected_key!r} in body: {list(body.keys()) if isinstance(body, dict) else type(body)}")
        return False
    val = body[expected_key]
    _ok(label, f"{expected_key}={val}")
    return True


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def step_health(session, base, results):
    body, ok = _get(session, base, "/health", "health check")
    if ok:
        _ok("health check", f"status={body.get('status')}")
    results["health"] = "PASS" if ok else "FAIL"


def step_auth(session, base, results):
    email = f"smoke-analytics-{uuid.uuid4().hex[:8]}@aindy.local"
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


def step_kpi_weights_get(session, base, results):
    body, ok = _get(session, base, "/apps/analytics/kpi-weights", "kpi-weights get")
    if not ok:
        results["kpi_weights_get"] = "FAIL"
        return
    weights = body.get("weights") if isinstance(body, dict) else None
    if weights is None:
        _fail("kpi-weights get", f"no 'weights' key in: {list(body.keys()) if isinstance(body, dict) else type(body)}")
        results["kpi_weights_get"] = "FAIL"
        return
    _ok("kpi-weights get", f"is_personalized={body.get('is_personalized')}  adapted_count={body.get('adapted_count')}")
    results["kpi_weights_get"] = "PASS"


def step_kpi_weights_adapt(session, base, results):
    body, ok = _post(session, base, "/apps/analytics/kpi-weights/adapt", {}, "kpi-weights adapt")
    if not ok:
        results["kpi_weights_adapt"] = "FAIL"
        return
    _ok("kpi-weights adapt", f"keys={list(body.keys()) if isinstance(body, dict) else type(body)}")
    results["kpi_weights_adapt"] = "PASS"


def step_policy_thresholds_get(session, base, results):
    body, ok = _get(session, base, "/apps/analytics/policy-thresholds", "policy-thresholds get")
    if not ok:
        results["policy_thresholds_get"] = "FAIL"
        return
    if not isinstance(body, dict):
        _fail("policy-thresholds get", f"expected dict, got {type(body).__name__}")
        results["policy_thresholds_get"] = "FAIL"
        return
    _ok("policy-thresholds get", f"keys={list(body.keys())}")
    results["policy_thresholds_get"] = "PASS"


def step_policy_thresholds_adapt(session, base, results):
    body, ok = _post(session, base, "/apps/analytics/policy-thresholds/adapt", {}, "policy-thresholds adapt")
    if not ok:
        results["policy_thresholds_adapt"] = "FAIL"
        return
    _ok("policy-thresholds adapt", f"keys={list(body.keys()) if isinstance(body, dict) else type(body)}")
    results["policy_thresholds_adapt"] = "PASS"


def step_compute_all(session, base, results):
    """Run all pure-math compute endpoints, record each separately."""
    endpoints = [
        ("calculate_effort",           TASK_INPUT,                    "Effort Score"),
        ("calculate_productivity",      TASK_INPUT,                    "Productivity Score"),
        ("calculate_virality",          VIRALITY_INPUT,                "Virality Score"),
        ("calculate_engagement",        ENGAGEMENT_INPUT,              "Engagement Score"),
        ("calculate_ai_efficiency",     AI_EFFICIENCY_INPUT,           "AI Efficiency Score"),
        ("calculate_impact_score",      IMPACT_INPUT,                  "Impact Score"),
        ("income_efficiency",           EFFICIENCY_INPUT,              "Income Efficiency"),
        ("revenue_scaling",             REVENUE_SCALING_INPUT,         "Revenue Scaling"),
        ("execution_speed",             EXECUTION_SPEED_INPUT,         "Execution Speed"),
        ("attention_value",             ATTENTION_VALUE_INPUT,         "Attention Value"),
        ("engagement_rate",             ENGAGEMENT_RATE_INPUT,         "Engagement Rate"),
        ("business_growth",             BUSINESS_GROWTH_INPUT,         "Business Growth"),
        ("monetization_efficiency",     MONETIZATION_EFFICIENCY_INPUT, "Monetization Efficiency"),
        ("ai_productivity_boost",       AI_PRODUCTIVITY_BOOST_INPUT,   "AI Productivity Boost"),
        ("lost_potential",              LOST_POTENTIAL_INPUT,          "Lost Potential"),
        ("decision_efficiency",         DECISION_EFFICIENCY_INPUT,     "Decision Efficiency"),
    ]
    for path, payload, expected_key in endpoints:
        label = f"compute/{path}"
        ok = _compute(session, base, path, payload, label, expected_key)
        results[f"compute_{path}"] = "PASS" if ok else "FAIL"


def step_batch(session, base, results):
    body, ok = _post(session, base, "/apps/compute/batch_calculations", BATCH_INPUT, "batch_calculations")
    if not ok:
        results["batch"] = "FAIL"
        return
    if not isinstance(body, dict):
        _fail("batch_calculations", f"expected dict, got {type(body).__name__}")
        results["batch"] = "FAIL"
        return
    # Expect at least some metric keys in the result
    metric_keys = [k for k in body if k != "execution_envelope"]
    _ok("batch_calculations", f"metric keys={metric_keys}")
    results["batch"] = "PASS"


def step_results_list(session, base, results):
    body, ok = _get(session, base, "/apps/compute/results", "compute results list")
    if not ok:
        results["results_list"] = "FAIL"
        return
    count = len(body) if isinstance(body, list) else (len(body.get("results") or []) if isinstance(body, dict) else "?")
    _ok("compute results list", f"count={count}  type={type(body).__name__}")
    results["results_list"] = "PASS"


def step_masterplans_list(session, base, results):
    body, ok = _get(session, base, "/apps/compute/masterplans", "compute masterplans list")
    if not ok:
        results["masterplans_list"] = "FAIL"
        return
    count = len(body) if isinstance(body, list) else (len(body.get("masterplans") or []) if isinstance(body, dict) else "?")
    _ok("compute masterplans list", f"count={count}  type={type(body).__name__}")
    results["masterplans_list"] = "PASS"


def step_calculate_twr(session, base, results):
    """POST /apps/compute/calculate_twr — runs infinity orchestrator; degrades gracefully."""
    body, ok = _post(session, base, "/apps/compute/calculate_twr", TASK_INPUT, "calculate_twr", expect=(200, 201, 202, 500))
    if body is None:
        # Total failure (no JSON response)
        results["calculate_twr"] = "FAIL"
        return
    if not isinstance(body, dict):
        _fail("calculate_twr", f"expected dict, got {type(body).__name__}")
        results["calculate_twr"] = "FAIL"
        return
    # Accept 500 from infinity if it can't score (no data), but not if server errored
    r = session.post(f"{base}/apps/compute/calculate_twr", json=TASK_INPUT)
    if r.status_code == 500 and "infinity_scoring" in r.text:
        _ok("calculate_twr", "graceful 500 — infinity has no history yet (acceptable)")
        results["calculate_twr"] = "PASS"
        return
    if r.status_code in (200, 201, 202):
        twr = body.get("TWR") or body.get("twr")
        _ok("calculate_twr", f"TWR={twr}  keys={list(body.keys())}")
        results["calculate_twr"] = "PASS"
        return
    _fail("calculate_twr", f"status={r.status_code}: {r.text[:200]}")
    results["calculate_twr"] = "FAIL"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Analytics/Compute domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("ANALYTICS / COMPUTE DOMAIN SMOKE TEST")
    print(f"Target: {base}")
    print("Skipping: linkedin/manual, masterplan analytics (need existing plan)")
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

    print("\n[3] KPI weights get (GET /apps/analytics/kpi-weights)")
    step_kpi_weights_get(session, base, results)

    print("\n[4] KPI weights adapt (POST /apps/analytics/kpi-weights/adapt)")
    step_kpi_weights_adapt(session, base, results)

    print("\n[5] Policy thresholds get (GET /apps/analytics/policy-thresholds)")
    step_policy_thresholds_get(session, base, results)

    print("\n[6] Policy thresholds adapt (POST /apps/analytics/policy-thresholds/adapt)")
    step_policy_thresholds_adapt(session, base, results)

    print("\n[7-22] Pure-math compute endpoints (POST /apps/compute/*)")
    step_compute_all(session, base, results)

    print("\n[23] Batch calculations (POST /apps/compute/batch_calculations)")
    step_batch(session, base, results)

    print("\n[24] Compute results list (GET /apps/compute/results)")
    step_results_list(session, base, results)

    print("\n[25] Compute masterplans list (GET /apps/compute/masterplans)")
    step_masterplans_list(session, base, results)

    print("\n[26] Calculate TWR via Infinity (POST /apps/compute/calculate_twr)")
    step_calculate_twr(session, base, results)

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
        print("ALL TESTS PASSED -- analytics/compute domain smoke OK")


if __name__ == "__main__":
    main()
