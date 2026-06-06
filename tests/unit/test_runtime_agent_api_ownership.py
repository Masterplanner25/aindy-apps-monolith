from __future__ import annotations

import pytest

from AINDY.routes import APP_ROUTERS
from AINDY.routes.agent_router import router as runtime_agent_router

pytestmark = pytest.mark.app_profile


def test_runtime_agent_router_is_not_app_surface_router():
    # agent_router extracted to plugin layer — no longer in runtime APP_ROUTERS
    assert runtime_agent_router not in APP_ROUTERS


def test_plugin_registry_owns_agent_router_after_bootstrap():
    import apps.bootstrap as bs
    from AINDY.platform_layer import registry

    bs._BOOTSTRAPPED = False
    registry._loaded_plugins.clear()
    registry._registered_apps.clear()
    registry._bootstrap_dependencies.clear()
    registry._routers.clear()
    registry._root_routers.clear()
    registry._legacy_root_routers.clear()
    registry.publish_degraded_domains(())

    bs.bootstrap()

    registered_prefixes = [getattr(router, "prefix", None) for router in registry.get_routers()]
    assert "/agent" in registered_prefixes


def test_monolith_agent_router_is_independent_of_runtime_router():
    from apps.agent.routes.agent_router import router as monolith_router

    # monolith now owns the canonical router — it is NOT the deprecated runtime copy
    assert monolith_router is not runtime_agent_router
