# aindy-apps-monolith

`aindy-apps-monolith` is the app/plugin-pack repository that depends on the
installed `aindy-runtime` package.

It owns:

- `apps/`
- `client/`
- `aindy_plugins.json`
- `alembic/`
- app-profile tests and helpers
- app-owned and shared app-facing docs

It does not vendor `AINDY/`. Runtime code, runtime-only entrypoints, and
runtime-only docs live in the separate `aindy-runtime` repo.

## Install

Install runtime first, then install the apps repo:

```bash
python -m pip install "aindy-runtime>=1.0,<2.0"
python -m pip install -e . --no-build-isolation
```

For local paired-repo validation when you are developing the runtime and apps
repos together from sibling checkouts:

```bash
python -m pip install -e ../aindy-runtime --no-deps --no-build-isolation
python -m pip install -e . --no-build-isolation
```

## Boot The App Profile

From the apps repo root:

```bash
aindy-runtime-api
```

Equivalent forms:

```bash
uvicorn AINDY.main:app
AINDY_APP_PLUGIN_MANIFEST=./aindy_plugins.json aindy-runtime-api
```

The app repo owns `aindy_plugins.json` and `apps.bootstrap`. The runtime owns
manifest parsing, plugin loading, and process entrypoints.

## Deployment Ownership

`aindy-apps-monolith` owns the app deployment layer:

- repo-root `aindy_plugins.json`
- `apps.bootstrap`
- `alembic/` and schema-migration operations for deployed app databases
- `client/` and app-hosted UI delivery
- app-profile startup documentation and app-profile validation

It consumes `aindy-runtime` as a dependency for:

- `aindy-runtime` / `aindy-runtime-api`
- runtime-only boot behavior
- runtime health, readiness, and `/api/version` compatibility metadata
- runtime public API and startup contracts

## Branch And PR Model

Active contribution model for this repo:

- protected branch: `main`
- pull requests should target: `main`
- feature work should branch from the current `main`

This repo does not use the archived monolith `develop`-targeting flow.

## Verify

Representative app-profile subset:

```bash
python -m pytest \
  tests/unit/test_app_manifest_bootstrap_contract.py \
  tests/unit/test_import_boundaries.py \
  tests/unit/test_runtime_agent_api_ownership.py \
  tests/unit/test_tasks_public_contract.py \
  tests/unit/test_analytics_public_contract.py \
  tests/unit/test_app_model_registration.py \
  tests/test_bootstrap_completeness.py \
  -m app_profile -q
```

Apps CI scope in `.github/workflows/app-ci.yml` is intentionally repo-owned:

- checkout `aindy-runtime` source in CI and install it explicitly before
  installing the apps repo
- verify that `AINDY` resolves from the installed runtime package
- smoke `GET /api/version` in app-profile mode and assert non-zero app plugins
- run cross-app import checks, bootstrap dependency validation, docs/API drift checks, and the full extracted app-profile pytest suite
- run the frontend unit test suite and build the client
- run a client Docker build smoke from `client/Dockerfile`

GitHub Actions note:

- until `aindy-runtime` is published to a package index, this workflow installs
  runtime from repo source rather than from `pip install "aindy-runtime>=1.0,<2.0"`
- if GitHub cannot read the runtime repo with the default token, set:
  - repository variable `AINDY_RUNTIME_REPO`
  - secret `AINDY_RUNTIME_CHECKOUT_TOKEN` with read access to that repo
- once runtime publication is live and reachable from GitHub Actions, this CI
  path should switch back to direct package installation by version range
- Playwright E2E is not in the default push/PR workflow yet; those tests are
  product/integration heavy and should be added separately once the extracted
  apps repo has a stable CI backend/auth fixture story

The apps repo does not publish a runtime package. Its staged release concern is
dependency coherence:

- the declared `aindy-runtime` range must stay bounded
- the declared range must match the runtime compatibility policy for the active
  runtime MAJOR series
- app-profile CI must run against an explicitly installed runtime package

CI ownership guidance lives in `docs/apps/CI_OWNERSHIP.md`.

Manual GitHub branch-protection and review settings guidance lives in
`docs/apps/GITHUB_SETTINGS_CHECKLIST.md`.

## Validated Split Check

Validated on `2026-05-17` in the extracted repo. One local validation run used
an editable sibling checkout of `aindy-runtime`:

```bash
python -m pip install -e ../aindy-runtime --no-deps --no-build-isolation
python -m pip install -e . --no-build-isolation
python -m pytest \
  tests/unit/test_app_manifest_bootstrap_contract.py \
  tests/unit/test_import_boundaries.py \
  tests/unit/test_runtime_dependency_contract.py \
  tests/unit/test_runtime_agent_api_ownership.py \
  tests/unit/test_tasks_public_contract.py \
  tests/unit/test_analytics_public_contract.py \
  tests/unit/test_app_model_registration.py \
  tests/test_bootstrap_completeness.py \
  -m app_profile -q
python -c "import os, json; os.environ.update({'DATABASE_URL':'sqlite://','MONGO_URL':'','AINDY_ALLOW_SQLITE':'1','OPENAI_API_KEY':'sk-test-placeholder','DEEPSEEK_API_KEY':'ds-test-placeholder','SECRET_KEY':'apps-integration-secret','AINDY_API_KEY':'apps-integration-api-key','PERMISSION_SECRET':'apps-integration-permission-secret','AINDY_SKIP_MONGO_PING':'1','SKIP_MONGO_PING':'1'}); from fastapi.testclient import TestClient; import AINDY.main as main; payload=TestClient(main.app, raise_server_exceptions=False).get('/api/version').json(); print(json.dumps(payload['runtime'], sort_keys=True)); print(json.dumps(payload['compatibility'], sort_keys=True))"
python scripts/check_app_imports.py
```

Observed result:

- app-profile `/api/version` reported `boot_profile=default-apps`
- `app_plugins_loaded` was `True`
- `app_plugin_count` was non-zero and `len(registry.get_registered_apps())` was `16`
- cross-app import boundary scan reported `33 declared, 0 undeclared`

Non-blocking bootstrap warnings seen during smoke validation:

- accepted `APP_DEPENDS_ON` ordering-gap warnings for deferred identity calls
- `apps.freelance.bootstrap` warns when `STRIPE_WEBHOOK_SECRET` is unset
