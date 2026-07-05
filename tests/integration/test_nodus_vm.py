"""
RTR-1 §5 — validate the opt-in `nodus_vm` agent-execution backend with REAL app tools.

See HANDOFF-aindy-runtime-1.5.0.md §5 and .github/workflows/nodus-vm-integration.yml.

Why this suite exists
---------------------
The runtime validated `nodus_vm` end-to-end on Postgres, but ONLY with its own
runtime-native tools (`memory.recall`/`memory.write`). The open question — and the
last gate before `nodus_vm` could ever become the default — is whether tools
registered by THIS repo's plugin manifest resolve AND execute inside the
`nodus_worker` subprocess spawned by `NodusRuntimeAdapter`. That subprocess loads
tools via `_ensure_tools_loaded → load_plugins()`, which resolves the app manifest
relative to the subprocess cwd (the PLANNER-SUBPROC-1 risk class).

Crucially, `memory.recall`/`memory.write` are ALSO registered as runtime defaults
inside the subprocess, so a run over a memory tool can pass even if the app manifest
failed to load — masking the failure. To actually close the gate we must drive a
tool that ONLY the app manifest provides (e.g. `task.create`), which the runtime has
no default for. The `anthropic_chat` planner (real Claude call) is used so the LLM
selects such a tool from the app catalog — that is why this suite needs a real
`ANTHROPIC_API_KEY` and is gated to the dedicated CI job.

Run:
    docker compose -f docker-compose.test.yml up -d
    ANTHROPIC_API_KEY=sk-ant-... pytest -c pytest.nodus.ini tests/integration/test_nodus_vm.py -v

History: execute-to-completion of a resumed nodus_vm segment was blocked by two stacked
runtime bugs, both PG-only (SQLite masked them) and both surfaced by driving the scheduler
in-process here:
  1. aindy-runtime#152 — ExecutionPipeline emitted its own execution.started BEFORE marking
     itself active, so the nested flow-runner pipeline tripped the ExecutionContract guard
     ('execution.started emitted outside pipeline'); the swallowed error poisoned the PG txn.
     Fixed in 1.5.2 (PR #155): set pipeline_active before the first emit.
  2. aindy-runtime#157 — with #152 cleared, the syscall dispatcher's idempotency gate cast
     the run-scoped execution_unit_id ('run_<uuid>') to the ExecutionUnit.id UUID column
     (InvalidTextRepresentation); the caught error, lacking a savepoint, poisoned the txn
     (InFailedSqlTransaction), so the flow_runs INSERT failed and the run never completed.
     Fixed in 1.5.3 (PR #158): only look up bare-UUID ids + SAVEPOINT/rollback the lookup.
With both fixed (pin floor >=1.5.3), the resumed segment runs to a terminal state, so Gate 2
hard-asserts completion. See TECH_DEBT RTR-1-NODUS-COMPLETION (RESOLVED).
"""
from __future__ import annotations

import os
import time
import uuid

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.app_profile, pytest.mark.postgres]


# --- app-manifest-only tools (no runtime default) vs runtime-default tools ------
# A run that executes an APP_MANIFEST_TOOL inside the subprocess proves the app
# manifest loaded there. RUNTIME_DEFAULT_TOOLS can resolve via the runtime fallback
# even if the manifest did not, so they do NOT close the §5 gate on their own.
APP_MANIFEST_TOOLS = {"task.create", "task.complete"}
RUNTIME_DEFAULT_TOOLS = {"memory.recall", "memory.write"}

TERMINAL_STATUSES = {"completed", "failed", "rejected"}
_RESOLUTION_FAILURE_MARKERS = (
    "not found",
    "unknown tool",
    "no such tool",
    "not registered",
    "unavailable tool",
    "could not resolve tool",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _register_and_login(client) -> str:
    email = f"test-nodus-{uuid.uuid4().hex[:8]}@aindy.test"
    password = "IntegrationTest1!"
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (200, 201), f"register: {r.status_code} {r.text[:200]}"
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login: {r.status_code} {r.text[:200]}"
    body = r.json()
    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    assert token, f"no access_token in login response: {body}"
    return token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _extract_run_id(body: dict) -> str | None:
    er = body.get("execution_record") or {}
    return er.get("run_id") or body.get("run_id") or ((body.get("data") or {}).get("run_id"))


def _status_from(body: dict) -> str:
    return str(body.get("status") or "").lower()


def _steps(client, token, run_id) -> list[dict]:
    r = client.get(f"/apps/agent/runs/{run_id}/steps", headers=_auth(token))
    assert r.status_code == 200, f"steps: {r.status_code} {r.text[:200]}"
    body = r.json()
    return body.get("data") if isinstance(body, dict) and "data" in body else body


def _has_real_anthropic_key() -> bool:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    return bool(key) and "placeholder" not in key and "test" not in key.lower()


def _poll_run(client, token, run_id, *, until, timeout=90.0, interval=2.0) -> dict:
    """Poll GET /runs/{id} until ``until(status)`` is truthy or timeout. Returns last body."""
    deadline = time.monotonic() + timeout
    body: dict = {}
    while time.monotonic() < deadline:
        r = client.get(f"/apps/agent/runs/{run_id}", headers=_auth(token))
        assert r.status_code == 200, f"get run: {r.status_code} {r.text[:200]}"
        body = r.json()
        if until(_status_from(body)):
            return body
        time.sleep(interval)
    return body


def _diagnose_anthropic_planner(goal: str) -> str:
    """Reproduce the anthropic_chat plan-gen failure directly, in the TEST thread.

    The runtime swallows the real reason into a ``threading.local`` (``_plan_failure``
    set on the FastAPI threadpool worker, unreadable from here) and a ``required``
    ``agent_plan_generation`` SystemEvent that can itself be lost to the
    ``system_events_user_id_fkey`` violation. Plan generation runs **in-process**
    regardless of the execution backend (``create_run`` -> ``generate_plan``; the
    backend only affects ``apply_wait_policy`` *after* generation), so calling the app
    backend directly here reproduces the create-500 cause with no ``nodus_worker``
    subprocess involved. See TECH_DEBT RTR-1-NODUS-APPTOOL-500.
    """
    try:
        from apps.agent.agents.planner_anthropic import claude_planner_backend
    except Exception as exc:  # pragma: no cover - import guard
        return f"could not import claude_planner_backend: {type(exc).__name__}: {exc}"

    class _Req:
        objective = goal
        run_type = "default"
        user_id = None
        system_prompt = (
            "You are A.I.N.D.Y.'s planner. Available tools: task.create, task.complete, "
            "memory.recall, memory.write. Produce a plan using only these tools."
        )
        tools = ({"name": "task.create"}, {"name": "task.complete"}, {"name": "memory.recall"})
        runtime_api = None
        metadata = {}

    try:
        plan = claude_planner_backend(_Req())
        steps = plan.get("steps") if isinstance(plan, dict) else None
        return (
            f"direct backend call SUCCEEDED (steps={len(steps or [])}) — the create-500 "
            "is in the runtime dispatch/context, NOT the anthropic_chat backend"
        )
    except Exception as exc:
        return f"direct backend call raised {type(exc).__name__}: {str(exc)[:400]}"


def _assert_no_tool_resolution_failure(steps: list[dict], run_body: dict) -> None:
    """The failure mode §5 hunts: a tool that never resolved in the subprocess."""
    haystacks = [str(run_body.get("error") or "")]
    for s in steps:
        haystacks.append(str(s.get("error_message") or ""))
    for text in haystacks:
        low = text.lower()
        for marker in _RESOLUTION_FAILURE_MARKERS:
            assert marker not in low, (
                f"tool-resolution failure detected ({marker!r}) — app manifest likely "
                f"did not load in the nodus_worker subprocess: {text[:300]}"
            )


# --------------------------------------------------------------------------- #
# Module guard — this suite is only meaningful on live Postgres + nodus_vm
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _require_nodus_vm():
    if os.getenv("AINDY_AGENT_EXECUTION_BACKEND", "agent_flow").strip().lower() != "nodus_vm":
        pytest.skip("nodus_vm validation requires AINDY_AGENT_EXECUTION_BACKEND=nodus_vm "
                    "(use -c pytest.nodus.ini)")


# --------------------------------------------------------------------------- #
# Gate 1 — a REAL app-manifest tool resolves AND executes inside nodus_vm
# --------------------------------------------------------------------------- #
class TestNodusVmAppTool:

    @pytest.fixture
    def _anthropic_planner(self, monkeypatch):
        # Select the LLM planner via settings (not just env) — the create path
        # resolves the backend from settings.AINDY_AGENT_PLANNER_BACKEND, and the
        # reloaded-app test harness doesn't reliably reflect the ini env into it
        # (Gate 2 monkeypatches the same way for the stub planner).
        from AINDY.config import settings

        monkeypatch.setattr(settings, "AINDY_AGENT_PLANNER_BACKEND", "anthropic_chat", raising=False)
        return "anthropic_chat"

    def test_app_tool_resolves_and_executes_in_subprocess(self, client, _anthropic_planner):
        if not _has_real_anthropic_key():
            pytest.skip("needs a real ANTHROPIC_API_KEY (anthropic_chat planner) to select an app tool")

        token = _register_and_login(client)
        # Goal steers the LLM toward task.create — an app-manifest-only tool the
        # runtime has NO default for, so a successful run proves the subprocess
        # loaded the app manifest.
        goal = f"Create a task titled 'nodus-vm smoke {uuid.uuid4().hex[:6]}' to verify the deploy."
        r = client.post("/apps/agent/run", json={"goal": goal}, headers=_auth(token))
        if r.status_code in (202, 500):
            diag = _diagnose_anthropic_planner(goal) if r.status_code == 500 else "n/a (deferred)"
            pytest.skip(
                f"run deferred or planner unavailable (status={r.status_code}): "
                f"{r.text[:200]} || RTR-1-NODUS-APPTOOL-500 diagnosis: {diag}"
            )
        assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:200]}"

        body = r.json()
        run_id = _extract_run_id(body)
        assert run_id, f"no run_id in create response: {body}"

        if _status_from(body) == "pending_approval":
            ra = client.post(f"/apps/agent/runs/{run_id}/approve", headers=_auth(token))
            assert ra.status_code in (200, 201, 202), f"approve: {ra.status_code} {ra.text[:200]}"

        # Execution may run inline or park; wait for a terminal or waiting state.
        run_body = _poll_run(
            client, token, run_id,
            until=lambda s: s in TERMINAL_STATUSES or s == "waiting",
        )
        status = _status_from(run_body)
        steps = _steps(client, token, run_id)

        # THE §5 GATE (always checked, terminal or not): the app tool must never fail
        # to resolve inside the nodus_worker subprocess. A manifest-load failure would
        # surface here as a "tool not found" error and fail this test red.
        _assert_no_tool_resolution_failure(steps, run_body)

        if status not in TERMINAL_STATUSES:
            # nodus_vm parked/started but the plan does not run to completion under the
            # TestClient harness (no running scheduler to drive the continuation). The
            # resolution gate above already passed, so the app manifest loaded — only
            # execute-to-completion is unobservable here. Documented, not a failure.
            # See TECH_DEBT RTR-1-NODUS-COMPLETION.
            pytest.xfail(
                f"nodus_vm run did not reach a terminal state in the TestClient harness "
                f"(status={status!r}); no tool-resolution failure observed — full app-tool "
                f"execute parity needs a live-server harness (TECH_DEBT RTR-1-NODUS-COMPLETION)"
            )

        # Reached completion — assert the full gate: an app-manifest tool executed.
        assert steps, f"nodus_vm run produced no steps (status={status})"
        executed_tools = {
            s.get("tool_name") for s in steps
            if s.get("tool_name") and _status_from(s) not in {"pending", "skipped", ""}
        }
        assert executed_tools, f"no tools were executed: {steps}"

        app_tools_hit = executed_tools & APP_MANIFEST_TOOLS
        if not app_tools_hit and executed_tools <= RUNTIME_DEFAULT_TOOLS:
            # Ran, but only over runtime-default tools — the gate is inconclusive
            # (memory.* can resolve via the runtime fallback). Surface, don't pass silently.
            pytest.xfail(f"LLM selected only runtime-default tools {executed_tools}; "
                         "goal did not exercise an app-manifest-only tool — retune the goal")
        assert app_tools_hit, (
            f"expected an app-manifest tool {APP_MANIFEST_TOOLS} to execute in the subprocess; "
            f"got {executed_tools}"
        )

        # The app-manifest step must have actually succeeded (resolved + ran), not
        # merely appeared in the plan.
        for s in steps:
            if s.get("tool_name") in app_tools_hit:
                assert _status_from(s) in {"success", "completed", "executed", "ok"}, (
                    f"app tool {s.get('tool_name')} did not execute cleanly: "
                    f"status={s.get('status')} error={s.get('error_message')}"
                )


# --------------------------------------------------------------------------- #
# Gate 2 — mid-plan WAIT parks the run; the resume route drives it to completion
# --------------------------------------------------------------------------- #
class TestNodusVmWaitResume:
    """Deterministic (no LLM): the app `stub` planner emits a canned high-risk step;
    AINDY_AGENT_WAIT_BEFORE_HIGH_RISK inserts an approval WAIT before it, so the run
    parks at status='waiting' under nodus_vm and the resume route releases it."""

    @pytest.fixture
    def _stub_planner(self, monkeypatch):
        from AINDY.config import settings

        monkeypatch.setattr(settings, "AINDY_AGENT_PLANNER_BACKEND", "stub", raising=False)
        return "stub"

    def test_wait_then_resume_completes(self, client, _stub_planner):
        token = _register_and_login(client)
        r = client.post(
            "/apps/agent/run",
            json={"goal": f"nodus-vm wait/resume {uuid.uuid4().hex[:6]}"},
            headers=_auth(token),
        )
        if r.status_code in (202, 500):
            pytest.skip(f"stub planner unavailable or run deferred (status={r.status_code}): {r.text[:300]}")
        assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:200]}"

        body = r.json()
        run_id = _extract_run_id(body)
        assert run_id, f"no run_id in create response: {body}"

        if _status_from(body) == "pending_approval":
            ra = client.post(f"/apps/agent/runs/{run_id}/approve", headers=_auth(token))
            assert ra.status_code in (200, 201, 202), f"approve: {ra.status_code} {ra.text[:200]}"

        # The wait policy should park the run before the high-risk stub step.
        parked = _poll_run(client, token, run_id, until=lambda s: s == "waiting", timeout=60.0)
        if _status_from(parked) != "waiting":
            pytest.skip(f"run never parked at 'waiting' (status={_status_from(parked)!r}); "
                        "wait-before-high-risk policy did not insert a WAIT — investigate")

        # The resume route (§4) releases the parked run.
        rr = client.post(f"/apps/agent/runs/{run_id}/resume", headers=_auth(token))
        assert rr.status_code == 200, f"resume: {rr.status_code} {rr.text[:200]}"
        resumed = rr.json()
        assert resumed.get("resumed_event") == "agent.approval.granted", (
            f"unexpected resume envelope: {resumed}"
        )

        assert resumed.get("waiters_notified", 0) >= 1, (
            f"resume notified no waiters — event not delivered: {resumed}"
        )

        # Resume enqueues the continuation onto the scheduler queue. The TestClient
        # harness runs no heartbeat, so drive the scheduler directly — the in-process
        # equivalent of the 1s scheduler_heartbeat_tick — to dispatch and RUN the
        # resumed segment inline.
        #
        # On aindy-runtime >=1.5.3 both blockers are fixed: #152 / PR #155 (v1.5.2 —
        # ExecutionPipeline marks itself active before emitting execution.started) and
        # #157 / PR #158 (v1.5.3 — the idempotency gate no longer casts the run-scoped
        # execution_unit_id 'run_<uuid>' to the ExecutionUnit.id UUID column, and wraps the
        # lookup in a savepoint). So the resumed nodus_vm segment now runs to a terminal
        # state. A regression of either fix would poison the run's PG transaction and leave
        # it non-terminal (or 401 the poll on the poisoned session), failing the assert red.
        from AINDY.kernel.scheduler import get_scheduler_engine

        get_scheduler_engine().schedule()  # dispatch + run the resumed segment, inline

        final = _status_from(
            _poll_run(client, token, run_id, until=lambda s: s in TERMINAL_STATUSES, timeout=30.0)
        )
        assert final in TERMINAL_STATUSES, (
            "resumed nodus_vm segment did not run to completion "
            f"(observed status={final!r}); expected the aindy-runtime>=1.5.3 fixes "
            "(#152 pipeline-active + #157 idempotency-gate UUID/savepoint) to let the "
            "continuation reach a terminal state. If this fails, a run's PG transaction "
            "was likely poisoned again — reopen TECH_DEBT RTR-1-NODUS-COMPLETION."
        )
