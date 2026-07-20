"""Identity domain bootstrap."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BOOTSTRAP_DEPENDS_ON: list[str] = []
IS_CORE_DOMAIN: bool = True
APP_DEPENDS_ON: list[str] = []


def register() -> None:
    _register_models()
    _register_router()
    _register_response_adapters()
    _register_events()
    _register_syscalls()
    _register_health_check()
    # Expose public surface for cross-domain callers.
    from apps.identity import public as identity_public  # noqa: F401


def _register_models() -> None:
    from AINDY.db.database import Base
    from AINDY.db.model_registry import register_models
    from AINDY.platform_layer.registry import register_symbols
    import apps.identity.models as identity_models

    register_models(identity_models.register_models)
    register_symbols(
        {
            name: value
            for name, value in vars(identity_models).items()
            if isinstance(value, type) and getattr(value, "metadata", None) is Base.metadata
        }
    )


def _register_router() -> None:
    from AINDY.platform_layer.registry import register_router
    from apps.identity.routes.identity_router import router as identity_router
    register_router(identity_router)


def _register_response_adapters() -> None:
    from AINDY.platform_layer.registry import register_response_adapter
    from AINDY.platform_layer.response_adapters import raw_json_adapter
    register_response_adapter("auth", raw_json_adapter)


def _register_events() -> None:
    from AINDY.platform_layer.event_service import register_event_handler
    register_event_handler("auth.register.completed", _handle_auth_register_completed)


def _register_syscalls() -> None:
    from apps.identity.syscalls.syscall_handlers import (
        register_identity_syscall_handlers,
    )

    register_identity_syscall_handlers()


def _handle_auth_register_completed(event: dict) -> None:
    """Provision a new account's starting state (identity row, score, first memory, agent run).

    The event dict delivered by ``dispatch_internal_event_handlers`` carries only
    ``event_id / event_type / payload / user_id / trace_id / source`` — there is deliberately
    NO ``db`` key (handler payloads are sanitized). This handler previously read
    ``event.get("db")`` and returned early on every signup, so signup initialization never ran
    and every account was left with no UserIdentity, no user_scores, no initial memory node and
    no initial agent run. Open our own session, as every other app event handler does.

    Failures are logged, never swallowed silently — the silence is what hid this.
    """
    from AINDY.db.database import SessionLocal
    from AINDY.db.models.user import User
    from AINDY.utils.uuid_utils import ensure_uuid
    from apps.identity.services.signup_initialization_service import initialize_signup_state

    user_id = event.get("user_id")
    if user_id is None:
        logger.warning("[identity] auth.register.completed had no user_id; skipping signup init")
        return

    user_id = ensure_uuid(user_id)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            logger.warning("[identity] signup init: user %s not found; skipping", user_id)
            return
        initialize_signup_state(db=db, user=user)
        logger.info("[identity] signup state initialized for user %s", user_id)
    except Exception:
        logger.exception("[identity] signup initialization FAILED for user %s", user_id)
        raise
    finally:
        db.close()


def identity_health_check() -> bool:
    from AINDY.db.database import SessionLocal
    from sqlalchemy import text

    try:
        from AINDY.db.models.user_identity import UserIdentity
        from apps.identity.services.identity_service import IdentityService
    except Exception as exc:
        raise RuntimeError(f"identity health import failed: {exc}") from exc

    _ = IdentityService
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db.query(UserIdentity.id).limit(1).all()
        return True
    finally:
        db.close()


def _register_health_check() -> None:
    from AINDY.platform_layer.domain_health import domain_health_registry
    from AINDY.platform_layer.registry import register_health_check

    domain_health_registry.register("identity", identity_health_check)
    register_health_check("identity", lambda: {"status": "ok"})
