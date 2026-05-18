## Summary

-
-

## Scope

<!-- App area touched: apps bootstrap, domains, client, migrations, docs, CI, etc. -->

## Validation

- [ ] App-owned CI/test impact was considered
- [ ] `python -m pytest tests -m app_profile -q` passes locally, or the gap is explained
- [ ] App-profile `/api/version` and plugin-loading behavior remain correct if affected
- [ ] Frontend tests/build were checked if `client/` changed
- [ ] Migration impact was reviewed if `alembic/` or SQLAlchemy models changed
- [ ] Runtime dependency/install implications were reviewed if `AINDY.*` usage changed

## Docs And Contracts

- [ ] App docs/contracts were updated if routes, bootstrap behavior, client behavior, or migration policy changed
- [ ] `aindy_plugins.json` / `apps.bootstrap` implications were reviewed if startup behavior changed
- [ ] CI/workflow ownership remains app-owned and does not reintroduce runtime-only scope

## Reviewer Notes

<!-- Risks, deployment implications, follow-up cleanup, or known warnings. -->
