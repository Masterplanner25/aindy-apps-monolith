"""Rate-limited routes must expose a `request` parameter typed as starlette Request.

Regression: `run_research_query` had a Pydantic body parameter *named* `request` while the
actual `Request` was named `http_request`. slowapi's `@limiter.limit` looks up the parameter
literally named `request` and asserts it is a starlette Request, so it grabbed the body and
raised "parameter `request` must be an instance of starlette.requests.Request" — surfacing to
the user as a bare 500 on every research query.

This guards the whole class: any app route decorated with a rate limiter must have its
`request` parameter (if it declares one) annotated as `Request`. A future endpoint that
repeats the swap fails here instead of 500ing in production.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest
from starlette.requests import Request

pytestmark = pytest.mark.app_profile

# Routers that apply slowapi rate limiting; the research router is the one the bug lived in.
_ROUTE_MODULES = [
    "apps.search.routes.research_results_router",
]


def _iter_route_functions(module):
    """Public functions defined in the module — i.e. the route handlers.

    Underscore-prefixed helpers (e.g. `_do_run_research_query`) are internal and never seen by
    slowapi, so a body param named `request` there is harmless and out of scope.
    """
    for name, obj in vars(module).items():
        if name.startswith("_"):
            continue
        if inspect.isfunction(obj) and obj.__module__ == module.__name__:
            yield name, obj


def test_research_query_request_param_is_a_starlette_request():
    module = importlib.import_module("apps.search.routes.research_results_router")
    fn = module.run_research_query
    params = inspect.signature(fn).parameters
    assert "request" in params, "run_research_query must expose a `request` parameter for slowapi"
    annotation = params["request"].annotation
    assert annotation is Request, (
        f"the `request` parameter must be typed starlette Request, got {annotation!r} — "
        "a Pydantic body must not be named `request` on a rate-limited route"
    )


def test_no_route_names_a_non_request_param_request():
    """Across the search route modules, a param named `request` must be a Request."""
    for mod_name in _ROUTE_MODULES:
        module = importlib.import_module(mod_name)
        for fn_name, fn in _iter_route_functions(module):
            params = inspect.signature(fn).parameters
            if "request" in params:
                ann = params["request"].annotation
                # Skip helpers that don't annotate; enforce only where a type is declared.
                if ann is not inspect.Parameter.empty:
                    assert ann is Request, (
                        f"{mod_name}.{fn_name}: parameter `request` is typed {ann!r}, "
                        "must be starlette Request"
                    )
