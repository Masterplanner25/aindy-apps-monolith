---
title: "Public Surface Migration Guide"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "platform-team"
---
# Public Surface Migration Guide

This document tracks breaking changes and migration steps for all public
surfaces. When a surface is bumped to a new major version, a section is
added here.

## Migration: LoopAdjustment ORM → Service Functions (analytics consumers)

**Affects:** analytics callers of automation.public.LoopAdjustment
**Status:** COMPLETE (Apps Prompt 3, verified 2026-07-05) — analytics no longer
imports the `LoopAdjustment` ORM; loop-adjustment reads/writes now go through the
automation syscalls (`sys.v1.automation.list_loop_adjustments`,
`create_loop_adjustment`, `update_loop_adjustment`). `automation.public` still
exports `LoopAdjustment` and `get_loop_adjustments` for backward compatibility;
the hard removal (automation.public v2.0) has not shipped.
**Target version:** automation.public v2.0

### Before

```python
from apps.automation.public import LoopAdjustment
rows = db.query(LoopAdjustment).filter(...).all()
```

### After

```python
from apps.automation.public import get_loop_adjustments
rows = get_loop_adjustments(user_id, db, limit=10)
```

The returned `rows` are plain dicts, not ORM objects. Access columns as
`row["prediction_accuracy"]` instead of `row.prediction_accuracy`.

---

(Add more migration sections here as surfaces evolve.)
