"""
eta_service.py — ETA projection for MasterPlans.

Projects a MasterPlan's completion against the user-declared anchor_date.

Projection is **plan-scoped** (only the plan's own tasks) and **cascade-aware**:
remaining work is bounded both by throughput (remaining / velocity) and by the
longest remaining dependency chain (critical-path depth), which cannot be
parallelized away. The dependency graph (critical_path / critical_weight) comes
from the existing `sys.v1.tasks.get_graph_context` syscall. When the graph is
unavailable it falls back to the legacy flat user-velocity estimate.

Public API:
    calculate_eta(db, masterplan_id, user_id) -> dict
    recalculate_all_etas(db)                  -> int  (plans updated)
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone, date
from typing import Any, Optional

from sqlalchemy.orm import Session

from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher
from AINDY.platform_layer.user_ids import require_user_id

from apps.masterplan.models import MasterPlan

logger = logging.getLogger(__name__)

VELOCITY_WINDOW_DAYS = 14
CONFIDENCE_HIGH_MIN_TASKS = 5
CONFIDENCE_MEDIUM_MIN_TASKS = 2


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dispatch_task_read(payload: dict, *, db: Session, user_id: str, capability: str) -> dict:
    syscall_name = str(payload.pop("_syscall"))
    ctx = SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id),
        capabilities=[capability],
        trace_id="",
        metadata={"_db": db},
    )
    result = get_dispatcher().dispatch(syscall_name, payload, ctx)
    if result.get("status") != "success":
        raise RuntimeError(result.get("error") or "task read syscall failed")
    return result.get("data") or {}


def _count_tasks(db: Session, *, user_id: str, status: str | None = None) -> int:
    payload: dict = {"_syscall": "sys.v1.task.count"}
    if status is not None:
        payload["status"] = status
    return int(
        _dispatch_task_read(payload, db=db, user_id=user_id, capability="task.read").get("count")
        or 0
    )


def _count_tasks_completed_since(db: Session, *, user_id: str, since: datetime) -> int:
    return int(
        _dispatch_task_read(
            {"_syscall": "sys.v1.task.count_completed_since", "since": since.isoformat()},
            db=db,
            user_id=user_id,
            capability="task.read",
        ).get("count")
        or 0
    )


def _graph_context(db: Session, user_id: str) -> dict:
    """Fetch the user's task graph (nodes + critical_weight/ready/blocked).

    Best-effort: returns {} if the graph syscall is unavailable so ETA degrades
    to the legacy flat-velocity estimate rather than failing.
    """
    try:
        return (
            _dispatch_task_read(
                {"_syscall": "sys.v1.tasks.get_graph_context", "user_id": str(user_id)},
                db=db,
                user_id=str(user_id),
                capability="task.read",
            )
            or {}
        )
    except Exception as exc:
        logger.warning("ETA graph context unavailable for %s: %s", user_id, exc)
        return {}


def _scope_plan_from_graph(graph: dict, plan_id: Any) -> Optional[dict]:
    """Scope the task graph to one plan's tasks and derive cascade metrics.

    Returns None when the graph has no nodes (caller falls back to legacy counts).
    ``critical_depth`` is the longest remaining dependency chain among the plan's
    incomplete tasks (max critical_weight); 1 means no chain (all independent).
    """
    nodes = (graph or {}).get("nodes") or {}
    if not nodes:
        return None

    critical_weight = graph.get("critical_weight") or {}
    ready = {_as_int(task_id) for task_id in (graph.get("ready") or [])}
    blocked = {_as_int(task_id) for task_id in (graph.get("blocked") or [])}
    plan_id_int = _as_int(plan_id)

    total = completed = blocked_tasks = ready_tasks = 0
    critical_depth = 0
    for node in nodes.values():
        if _as_int(node.get("masterplan_id")) != plan_id_int:
            continue
        total += 1
        if str(node.get("status") or "") == "completed":
            completed += 1
            continue
        task_id = _as_int(node.get("task_id"))
        depth = _as_int(critical_weight.get(task_id, critical_weight.get(str(task_id)))) or 1
        critical_depth = max(critical_depth, depth)
        if task_id in ready:
            ready_tasks += 1
        elif task_id in blocked:
            blocked_tasks += 1

    return {
        "total": total,
        "completed": completed,
        "remaining": max(total - completed, 0),
        "critical_depth": critical_depth,
        "blocked_tasks": blocked_tasks,
        "ready_tasks": ready_tasks,
    }


def _project_days(remaining: int, velocity: float, critical_depth: int) -> float:
    """Days to finish ``remaining`` work at ``velocity`` tasks/day.

    Cascade-aware: a dependency chain of depth D is sequential and cannot be
    parallelized away, so it imposes a floor of ``D / min(velocity, 1.0)`` days.
    The projection is the larger of the throughput estimate and that floor, so
    deep chains push the date out even when raw throughput looks fast.
    """
    if velocity <= 0 or remaining <= 0:
        return 0.0
    throughput_days = remaining / velocity
    chain_rate = min(velocity, 1.0)
    sequential_days = (critical_depth / chain_rate) if (critical_depth > 1 and chain_rate > 0) else 0.0
    return max(throughput_days, sequential_days)


def _confidence_label(velocity: float, completed_in_window: int) -> str:
    if velocity == 0 or completed_in_window < CONFIDENCE_MEDIUM_MIN_TASKS:
        return "insufficient_data"
    if completed_in_window >= CONFIDENCE_HIGH_MIN_TASKS:
        return "high"
    if completed_in_window >= CONFIDENCE_MEDIUM_MIN_TASKS:
        return "medium"
    return "low"


def _total_tasks_for_user(db: Session, user_id: str) -> int:
    return _count_tasks(db, user_id=str(require_user_id(user_id)))


def _completed_tasks_for_user(db: Session, user_id: str) -> int:
    return _count_tasks(db, user_id=str(require_user_id(user_id)), status="completed")


def calculate_eta(db: Session, masterplan_id: int, user_id: str) -> dict:
    """
    Compute a plan-scoped, cascade-aware ETA projection for a single MasterPlan
    and persist the results.

    Returns:
        dict with keys: velocity, projected_completion_date, days_ahead_behind,
        eta_confidence, anchor_date, total_tasks, completed_tasks, remaining_tasks,
        critical_depth, blocked_tasks, ready_tasks, projection_basis
    """
    owner_user_id = require_user_id(user_id)
    plan = (
        db.query(MasterPlan)
        .filter(MasterPlan.id == masterplan_id, MasterPlan.user_id == owner_user_id)
        .first()
    )
    if not plan:
        raise ValueError(f"MasterPlan {masterplan_id} not found for user {user_id}")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=VELOCITY_WINDOW_DAYS)
    tasks_in_window = _count_tasks_completed_since(db, user_id=owner_user_id, since=cutoff)
    velocity = tasks_in_window / VELOCITY_WINDOW_DAYS

    # Plan-scoped, cascade-aware counts from the dependency graph; fall back to
    # legacy user-wide counts when the graph is unavailable.
    scope = _scope_plan_from_graph(_graph_context(db, owner_user_id), plan.id)
    if scope is not None:
        total = scope["total"]
        completed = scope["completed"]
        remaining = scope["remaining"]
        critical_depth = scope["critical_depth"]
        blocked_tasks = scope["blocked_tasks"]
        ready_tasks = scope["ready_tasks"]
        projection_basis = "cascade"
    else:
        total = _total_tasks_for_user(db, owner_user_id)
        completed = _completed_tasks_for_user(db, owner_user_id)
        remaining = max(total - completed, 0)
        critical_depth = 0
        blocked_tasks = 0
        ready_tasks = 0
        projection_basis = "velocity"

    projected: Optional[date] = None
    days_ahead_behind: Optional[int] = None

    if velocity > 0:
        days_needed = _project_days(remaining, velocity, critical_depth)
        projected = (now + timedelta(days=days_needed)).date()
        if plan.anchor_date:
            anchor = plan.anchor_date.date() if hasattr(plan.anchor_date, "date") else plan.anchor_date
            days_ahead_behind = (anchor - projected).days
    else:
        projection_basis = "insufficient_data"

    confidence = _confidence_label(velocity, tasks_in_window)

    # Persist to plan
    plan.current_velocity = velocity
    plan.projected_completion_date = projected
    plan.days_ahead_behind = days_ahead_behind
    plan.eta_last_calculated = now
    plan.eta_confidence = confidence
    db.commit()

    return {
        "masterplan_id": masterplan_id,
        "anchor_date": plan.anchor_date.isoformat() if plan.anchor_date else None,
        "velocity": velocity,
        "projected_completion_date": projected.isoformat() if projected else None,
        "days_ahead_behind": days_ahead_behind,
        "eta_confidence": confidence,
        "total_tasks": total,
        "completed_tasks": completed,
        "remaining_tasks": remaining,
        "critical_depth": critical_depth,
        "blocked_tasks": blocked_tasks,
        "ready_tasks": ready_tasks,
        "projection_basis": projection_basis,
        "eta_last_calculated": plan.eta_last_calculated.isoformat(),
    }


def recalculate_all_etas(db: Session) -> int:
    """
    Recalculate ETA for every MasterPlan that has an anchor_date set.
    Called by the daily APScheduler job.
    Returns the count of plans updated.
    """
    plans = (
        db.query(MasterPlan)
        .filter(MasterPlan.anchor_date.isnot(None))
        .all()
    )
    updated = 0
    for plan in plans:
        try:
            calculate_eta(db=db, masterplan_id=plan.id, user_id=plan.user_id)
            updated += 1
        except Exception as exc:
            logger.warning("ETA recalc failed for plan %s: %s", plan.id, exc)
    return updated
