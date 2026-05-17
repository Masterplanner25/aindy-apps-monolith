---
title: "Runtime Dependency"
last_verified: "2026-05-11"
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

Validated on `2026-05-11`:

- installed runtime version: `1.0.0`
- apps repo dependency: `aindy-runtime>=1.0,<2.0`
- runtime `/api/version` recommendation: `>=1.0,<2.0`

This is a staged release/dependency contract. It is ready for use in CI and
release preparation, but it does not imply that a new runtime release has
already been published externally.

## Current CI Install Strategy

GitHub Actions in this repo must be runnable before `aindy-runtime` is
published to an index that CI can install from.

Current staged strategy:

- keep the declared dependency contract in `pyproject.toml` as
  `aindy-runtime>=1.0,<2.0`
- in CI only, check out the runtime repo and install `aindy-runtime` from that
  source tree
- verify that the installed runtime still reports the expected compatibility
  metadata through `/api/version`

GitHub workflow behavior:

- default runtime checkout target: `${owner}/aindy-runtime`
- optional override: repository variable `AINDY_RUNTIME_REPO`
- optional explicit token for private/cross-repo checkout:
  `AINDY_RUNTIME_CHECKOUT_TOKEN`

This avoids pretending that runtime publication is complete while still
preserving the long-term packaged-runtime contract.

## Startup Contract

The apps repo owns:

- `aindy_plugins.json`
- `apps.bootstrap`
- app bootstrap ordering and degraded-domain policy

The runtime package owns:

- `aindy-runtime-api`
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

Once runtime publication is fully real and GitHub Actions can install the
intended version range directly, app CI should switch back from source checkout
to normal package installation for `aindy-runtime>=1.0,<2.0`.

Canonical app-profile startup from this repo root:

```bash
aindy-runtime-api
```

Equivalent explicit-manifest form:

```bash
AINDY_APP_PLUGIN_MANIFEST=./aindy_plugins.json aindy-runtime-api
```

## Runtime Docs

When this repo references runtime contracts such as the public API boundary,
runtime-only deployment, DB ownership, or compatibility policy, treat those as
living in the separate `aindy-runtime` repo.
