"""Freelance domain syscall handlers.

Exposes the freelance domain's cross-domain read seam. Currently: the revenue performance
signals the analytics/Infinity support state fetches via `sys.v1.freelance.get_performance_signals`
(re-tether — mirrors the social domain's `get_performance_signals` syscall).
"""
from __future__ import annotations

from AINDY.kernel.syscall_registry import SyscallContext, register_syscall


def _session_from_context(ctx: SyscallContext):
    from AINDY.db.database import SessionLocal

    external_db = ctx.metadata.get("_db")
    if external_db is not None:
        return external_db, False
    return SessionLocal(), True


def _handle_freelance_performance_signals(payload: dict, ctx: SyscallContext) -> dict:
    from apps.freelance.services.freelance_performance_service import (
        get_freelance_performance_signals,
    )

    db, owns_session = _session_from_context(ctx)
    try:
        signals = list(
            get_freelance_performance_signals(
                db,
                user_id=payload.get("user_id") or ctx.user_id or None,
                limit=int(payload.get("limit", 3) or 3),
            )
            or []
        )
        return {"signals": signals, "count": len(signals)}
    finally:
        if owns_session:
            db.close()


def _handle_freelance_optimize_pricing(payload: dict, ctx: SyscallContext) -> dict:
    from apps.freelance.services.revenue_intelligence_service import RevenueIntelligenceService

    db, owns_session = _session_from_context(ctx)
    try:
        svc = RevenueIntelligenceService(db=db, user_id=ctx.user_id)
        if bool(payload.get("apply", False)):
            return svc.apply(trigger=payload.get("trigger", "agent"))
        return {"dry_run": True, **svc.plan()}
    finally:
        if owns_session:
            db.close()


def register_freelance_syscall_handlers() -> None:
    register_syscall(
        name="sys.v1.freelance.get_performance_signals",
        handler=_handle_freelance_performance_signals,
        capability="freelance.read",
        description="Recent realized-revenue signals for the Infinity support state (re-tether).",
        stable=False,
    )
    register_syscall(
        name="sys.v1.freelance.optimize_pricing",
        handler=_handle_freelance_optimize_pricing,
        capability="freelance.optimize",
        description="Recommend/apply gated, revertible service-price adjustments from realized outcomes.",
        stable=False,
    )
