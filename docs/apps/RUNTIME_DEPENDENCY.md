---
title: "Runtime Dependency"
last_verified: "2026-07-18"
api_version: "1.0"
status: current
owner: "platform-team"
---
# Runtime Dependency

`aindy-apps-monolith` depends on the separately packaged `aindy-runtime`
distribution.

This repo does not own `AINDY/`, runtime-only entrypoints, or runtime-only
documentation. Those live in the `aindy-runtime` repo and are consumed here as
published contracts.

## Package Contract

Recommended dependency range:

```toml
aindy-runtime>=1.0,<2.0
```

The upper bound is required. The apps repo should not accept unbounded runtime
upgrades.

Validated on `2026-07-19`:

- installed runtime version: `1.10.0`
- apps repo dependency (pinned in `pyproject.toml`): `aindy-runtime>=1.10.0,<2.0`
- runtime `/api/version` recommendation: `>=1.0,<2.0`
- app-profile boot smoke on 1.10.0: `boot_profile=default-apps`, `app_plugins_loaded=True`, `app_plugin_count=17`

Floor raised to `1.10.0` to adopt v1.10.0 (additive/opt-in, no schema change): ships the
**RT-MEMTXN-LEAK-1** fix (the browser sign-in blocker — memory-node reads no longer leak
`idle in transaction` connections; app-side repro re-verification tracked in
`RUNTIME_FEATURE_REQUESTS.md`), **closes NODUS-WARMPOOL-1** (warm `nodus_worker` pool,
Phases 1–3 — opt-in via `AINDY_NODUS_WARM_POOL=true`, default off), and canonical
`UI_CONTRACT` platform routes.

Prior floor `1.9.0` adopted v1.9.0 (additive/opt-in, no schema change): **FR-5** —
native Nodus workflows can now reach app logic (`run_nodus_workflow` gains a
`capability_token` param so `call_tool` steps can be granted capabilities, and the VM's
`sys()` resolves app-registered syscalls), unblocking Nodus-native reasoning execution;
plus NODUS-WARMPOOL-1 Option A (VM cold-start off the script budget). App-side adoption of
the Nodus reasoning routing lands in a follow-on PR.

Prior floor `1.8.0` adopted v1.8.0: FR-1 connector-registration hook +
capability-enforced outbound boundary (`register_connector`), FR-3
`NEXT_ACTION_DISPATCHED` dispatch-outcome contract, the FR-4 / DOCS-BUCKET-A-1
error-handling-policy runtime/app split, plus a `setuptools>=83.0.0` (CVE-2026-59890)
security bump and `nodus-lang 4.1.0` / `nltk 3.10.0`.

The floor stays at or above `1.5.3` for **both** nodus_vm execute-to-completion fixes (first shipped in v1.5.2 / v1.5.3): aindy-runtime
#152 / PR #155 (v1.5.2 — `ExecutionPipeline.run()` marks itself active before emitting its
own `execution.started`) and aindy-runtime #157 / PR #158 (v1.5.3 — the syscall idempotency
gate no longer casts a run-scoped `execution_unit_id` to a UUID column and wraps the lookup
in a savepoint). Together they let a resumed nodus_vm segment run to a terminal state; Gate 2
of `tests/integration/test_nodus_vm.py` hard-asserts that completion. See TECH_DEBT
`RTR-1-NODUS-COMPLETION`.

`aindy-runtime` is published on PyPI (`PYPI-PUBLISH-1` is closed), so this is the
live, published dependency contract — not a pre-publication staging arrangement.

## CI Install Strategy

`aindy-runtime` is installed from PyPI as a normal pinned dependency:

- the declared dependency in `pyproject.toml` is `aindy-runtime>=1.9.0,<2.0`
- CI installs it via `pip install -e .[test]` (no runtime-repo checkout, no source
  install)
- CI verifies the installed runtime version and that `/api/version` reports the
  expected compatibility metadata

GitHub workflow behavior:

- CI checks out only this repo and resolves `aindy-runtime` from PyPI within the
  pinned range; there is no runtime-repo checkout or `AINDY_RUNTIME_*` token.

This is the published packaged-runtime contract in steady state.

## Startup Contract

The apps repo owns:

- `aindy_plugins.json`
- `apps.bootstrap`
- app bootstrap ordering and degraded-domain policy

The runtime package owns:

- `aindy-runtime serve`
- `aindy-runtime`
- manifest parsing and profile selection
- plugin loading
- runtime-only boot

Deployment boundary:

- this repo owns app-profile deployment inputs such as `aindy_plugins.json`,
  `apps.bootstrap`, `alembic/`, and `client/`
- the runtime repo owns runtime-only deployment guidance, runtime packaging,
  and standalone runtime boot surfaces

## Release Staging Expectation

When the runtime repo stages a new release:

1. the runtime version is bumped in `AINDY/_version.py`
2. the runtime staged build verifies `/api/version` compatibility metadata
3. this repo keeps or updates its bounded dependency range deliberately
4. app-profile CI runs against the target runtime version before adoption

The apps repo should not move to an unbounded runtime dependency such as
`aindy-runtime>=1.0`.

App CI installs `aindy-runtime` directly from PyPI within the pinned range; bump
the lower bound deliberately when adopting a newer runtime release.

Canonical app-profile startup from this repo root:

```bash
aindy-runtime serve
```

Equivalent explicit-manifest form:

```bash
AINDY_APP_PLUGIN_MANIFEST=./aindy_plugins.json aindy-runtime serve
```

## Runtime Docs

When this repo references runtime contracts such as the public API boundary,
runtime-only deployment, DB ownership, or compatibility policy, treat those as
living in the separate `aindy-runtime` repo.
