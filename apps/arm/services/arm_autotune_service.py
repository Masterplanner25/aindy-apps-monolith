"""
ARM Auto-Tune Service — the closed half of Reflect -> Adjust.

``ARMConfigSuggestionEngine`` already produces an ``auto_apply_safe`` set of
low-risk config changes but nothing consumed it — auto-application was deferred to
"Phase 2/3". This service *is* that consumer: it takes ``auto_apply_safe`` and
applies it behind a conservative safety gate, records an auditable, revertible log
row, and propagates the change like ``PUT /arm/config`` does.

The gate (``evaluate_autotune_gate``) is a pure function so it can be unit-tested
without a database. Everything that touches the DB lives on ``ARMAutoTuneService``.

Safety gate (all must pass for a change to auto-apply):
  * whitelist   — only numeric tuning knobs; never model/extension/priority defaults
  * min sessions — don't tune on noise (< MIN_SESSIONS samples => skip all)
  * bounds      — every new value is clamped to a sane absolute range
  * cooldown    — a key auto-changed recently is left alone (prevents oscillation)
  * no-op       — a change equal to the current value is skipped
  * max changes — at most MAX_CHANGES_PER_RUN applied in a single run
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import require_user_id
from apps.arm.dao import arm_autotune_dao, arm_config_dao
from apps.arm.services.arm_metrics_service import (
    ARMConfigSuggestionEngine,
    ARMMetricsService,
)
from apps.arm.services.deepseek.config_manager_deepseek import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


# ── Gate policy ───────────────────────────────────────────────────────────────

# Numeric knobs only. Model ids, allowed_extensions, and task-priority defaults are
# deliberately excluded — an auto-tuner must never silently swap the model or widen
# the file-type surface, even if a future suggestion were tagged "low" risk.
AUTO_TUNE_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "temperature",
        "retry_limit",
        "retry_delay_seconds",
        "max_chunk_tokens",
        "max_output_tokens",
        "max_file_size_bytes",
    }
)

# Absolute clamps — independent of the suggestion engine's own step math, so a bad
# suggestion can never push a value out of a safe operating range.
AUTO_TUNE_BOUNDS: dict[str, tuple[float, float]] = {
    "temperature": (0.1, 1.0),
    "retry_limit": (1, 5),
    "retry_delay_seconds": (1, 10),
    "max_chunk_tokens": (1000, 8000),
    "max_output_tokens": (500, 4000),
    "max_file_size_bytes": (50_000, 500_000),
}

MIN_SESSIONS = 5
MAX_CHANGES_PER_RUN = 3
COOLDOWN_HOURS = 6


def _clamp(param: str, value):
    lo, hi = AUTO_TUNE_BOUNDS[param]
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def evaluate_autotune_gate(
    bundle: dict,
    current_config: dict,
    metrics: dict,
    recently_changed_keys: set[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Decide which of the suggestion engine's ``auto_apply_safe`` changes may be
    applied. Pure: no I/O. Returns ``(applied, skipped)``.

    ``applied`` items: {param, old, new, metric, reason, risk}
    ``skipped`` items: {param, suggested, reason}
    """
    recently_changed_keys = recently_changed_keys or set()
    applied: list[dict] = []
    skipped: list[dict] = []

    candidates = bundle.get("auto_apply_safe", []) or []

    total_sessions = int(metrics.get("total_sessions", 0) or 0)
    if total_sessions < MIN_SESSIONS:
        for suggestion in candidates:
            for param, new_val in (suggestion.get("config_change") or {}).items():
                skipped.append(
                    {
                        "param": param,
                        "suggested": new_val,
                        "reason": f"insufficient sessions ({total_sessions} < {MIN_SESSIONS})",
                    }
                )
        return applied, skipped

    seen_params: set[str] = set()

    for suggestion in candidates:
        # Defense-in-depth: only genuinely low-risk suggestions are eligible.
        if suggestion.get("risk") != "low":
            continue
        metric = suggestion.get("metric")
        reason = suggestion.get("suggestion") or suggestion.get("issue") or ""

        for param, new_val in (suggestion.get("config_change") or {}).items():
            if param not in AUTO_TUNE_ALLOWED_KEYS:
                skipped.append(
                    {"param": param, "suggested": new_val, "reason": "param not in auto-tune whitelist"}
                )
                continue
            if param in seen_params:
                skipped.append(
                    {"param": param, "suggested": new_val, "reason": "duplicate param in this run"}
                )
                continue
            if param in recently_changed_keys:
                seen_params.add(param)
                skipped.append(
                    {"param": param, "suggested": new_val, "reason": f"cooldown: changed within {COOLDOWN_HOURS}h"}
                )
                continue

            bounded = _clamp(param, new_val)
            current_val = current_config.get(param)
            if current_val is not None and bounded == current_val:
                seen_params.add(param)
                skipped.append(
                    {"param": param, "suggested": new_val, "reason": "no-op (already at value)"}
                )
                continue

            seen_params.add(param)
            if len(applied) >= MAX_CHANGES_PER_RUN:
                skipped.append(
                    {"param": param, "suggested": new_val, "reason": f"exceeds max {MAX_CHANGES_PER_RUN} changes/run"}
                )
                continue

            applied.append(
                {
                    "param": param,
                    "old": current_val,
                    "new": bounded,
                    "metric": metric,
                    "reason": reason,
                    "risk": "low",
                }
            )

    return applied, skipped


# ── Service ───────────────────────────────────────────────────────────────────

class ARMAutoTuneService:
    """Per-user consumer of ``auto_apply_safe`` with audit + revert."""

    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = require_user_id(user_id)
        self.config_key = str(self.user_id)

    # ── reads ─────────────────────────────────────────────────────────────────

    def _current_config(self) -> dict:
        row = arm_config_dao.get_config(self.db, user_id=self.config_key)
        if row is None:
            return DEFAULT_CONFIG.copy()
        return {key: getattr(row, key) for key in DEFAULT_CONFIG.keys()}

    def _metrics(self, window: int) -> dict:
        return ARMMetricsService(db=self.db, user_id=self.config_key).get_all_metrics(window=window)

    @staticmethod
    def _metrics_snapshot(metrics: dict) -> dict:
        return {
            "decision_efficiency": metrics.get("decision_efficiency", {}).get("score", 0),
            "execution_speed_avg": metrics.get("execution_speed", {}).get("average", 0),
            "ai_productivity_ratio": metrics.get("ai_productivity_boost", {}).get("ratio", 0),
            "waste_percentage": metrics.get("lost_potential", {}).get("waste_percentage", 0),
            "learning_trend": metrics.get("learning_efficiency", {}).get("trend", "insufficient data"),
            "total_sessions": metrics.get("total_sessions", 0),
        }

    def plan(self, window: int = 30) -> dict:
        """Dry run: compute what auto-tune *would* apply, without persisting."""
        current_config = self._current_config()
        metrics = self._metrics(window)
        bundle = ARMConfigSuggestionEngine(
            current_config=current_config, metrics=metrics
        ).generate_suggestions()

        since = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)
        cooldown_keys = arm_autotune_dao.recent_changed_keys(self.db, self.config_key, since)

        applied, skipped = evaluate_autotune_gate(
            bundle, current_config, metrics, recently_changed_keys=cooldown_keys
        )
        return {
            "applied": applied,
            "skipped": skipped,
            "prior_config": current_config,
            "metrics_snapshot": self._metrics_snapshot(metrics),
            "would_change": bool(applied),
        }

    # ── writes ────────────────────────────────────────────────────────────────

    def apply(self, window: int = 30, trigger: str = "manual") -> dict:
        """Apply the gated changes, persist config + an audit row, propagate."""
        proposal = self.plan(window=window)
        applied = proposal["applied"]

        if not applied:
            return {
                "status": "no_change",
                "dry_run": False,
                "applied": [],
                "skipped": proposal["skipped"],
                "config": proposal["prior_config"],
                "log_id": None,
            }

        prior_config = proposal["prior_config"]

        updated_row = arm_config_dao.upsert_config(
            self.db,
            user_id=self.config_key,
            **{c["param"]: c["new"] for c in applied},
        )
        resulting_config = {key: getattr(updated_row, key) for key in DEFAULT_CONFIG.keys()}

        log = arm_autotune_dao.create_log(
            self.db,
            user_id=self.config_key,
            trigger=trigger,
            applied=applied,
            skipped=proposal["skipped"],
            prior_config=prior_config,
            resulting_config=resulting_config,
            metrics_snapshot=proposal["metrics_snapshot"],
        )

        self._notify_config_changed([c["param"] for c in applied], resulting_config)

        return {
            "status": "applied",
            "dry_run": False,
            "applied": applied,
            "skipped": proposal["skipped"],
            "config": resulting_config,
            "log_id": str(log.id),
        }

    def revert(self, log_id) -> dict:
        """Restore the config snapshot captured before an auto-tune run."""
        log = arm_autotune_dao.get_log(self.db, log_id, user_id=self.config_key)
        if log is None:
            return {"status": "not_found", "log_id": str(log_id)}
        if log.reverted:
            return {"status": "already_reverted", "log_id": str(log.id)}

        prior = log.prior_config or {}
        restore = {k: v for k, v in prior.items() if k in DEFAULT_CONFIG}
        restored_row = arm_config_dao.upsert_config(self.db, user_id=self.config_key, **restore)
        arm_autotune_dao.mark_reverted(self.db, log.id, user_id=self.config_key)

        config = {key: getattr(restored_row, key) for key in DEFAULT_CONFIG.keys()}
        reverted_keys = [c["param"] for c in (log.applied or []) if c.get("param")]
        self._notify_config_changed(reverted_keys, config)

        return {"status": "reverted", "log_id": str(log.id), "config": config}

    def history(self, limit: int = 20) -> list[dict]:
        rows = arm_autotune_dao.list_logs(self.db, self.config_key, limit=limit)
        return [self._log_to_dict(row) for row in rows]

    # ── side effects (mirror PUT /arm/config) ──────────────────────────────────

    def _notify_config_changed(self, changed_keys: list[str], config: dict) -> None:
        from apps.arm.bootstrap import ARM_CONFIG_CHANNEL, _invalidate_arm_analyzer_cache

        _invalidate_arm_analyzer_cache()
        try:
            from AINDY.platform_layer.registry import emit_event

            emit_event(
                "arm.config.updated",
                {"updated_by": self.config_key, "channel": ARM_CONFIG_CHANNEL, "source": "autotune"},
            )
        except Exception as exc:  # non-fatal
            logger.warning("[arm.autotune] config invalidation emit failed: %s", exc)
        try:
            from AINDY.core.execution_signal_helper import queue_system_event

            queue_system_event(
                db=self.db,
                event_type="arm.config.updated",
                user_id=self.config_key,
                source="arm.autotune",
                payload={
                    "updated_keys": list(changed_keys),
                    "config": config,
                    "channel": ARM_CONFIG_CHANNEL,
                    "autotune": True,
                },
                required=False,
            )
        except Exception as exc:  # non-fatal
            logger.warning("[arm.autotune] system event queue failed: %s", exc)

    @staticmethod
    def _log_to_dict(row) -> dict:
        return {
            "id": str(row.id),
            "trigger": row.trigger,
            "applied": row.applied or [],
            "skipped": row.skipped or [],
            "prior_config": row.prior_config or {},
            "resulting_config": row.resulting_config or {},
            "metrics_snapshot": row.metrics_snapshot or {},
            "reverted": bool(row.reverted),
            "reverted_at": row.reverted_at.isoformat() if row.reverted_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
