"""Memory domain bootstrap."""
from __future__ import annotations

BOOTSTRAP_DEPENDS_ON: list[str] = []
IS_CORE_DOMAIN: bool = False
APP_DEPENDS_ON: list[str] = []


def register() -> None:
    _register_routers()


def _register_routers() -> None:
    from AINDY.platform_layer.registry import register_router
    from apps.memory.routes.memory_metrics_router import router as metrics_router
    from apps.memory.routes.memory_trace_router import router as trace_router
    register_router(metrics_router)
    register_router(trace_router)
