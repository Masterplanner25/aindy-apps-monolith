"""
Adoption test for runtime FR-2 (register_nodus_workflow).

Verifies the app's native Nodus reasoning workflow compiles and registers through
the runtime hook. Hermetic: registration uses db=None (in-memory) and compilation is
parse-only — no DB, no scheduler, no network.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from apps.analytics import bootstrap

pytestmark = pytest.mark.app_profile

_ND_PATH = Path(bootstrap.__file__).resolve().parent / "nodus" / "reasoning_apply_v1.nd"


def test_reasoning_nd_source_compiles():
    from AINDY.runtime.nodus_flow_compiler import compile_nodus_flow

    graph = compile_nodus_flow(_ND_PATH.read_text(encoding="utf-8"))
    assert graph["workflow_name"] == "reasoning_apply_v1"


def test_bootstrap_registers_reasoning_workflow():
    from AINDY.runtime.nodus_workflow_registry import get_nodus_workflow

    bootstrap._register_nodus_workflows()

    meta = get_nodus_workflow("reasoning_apply_v1")
    assert meta is not None
    assert meta["kind"] == "flow-graph"
    assert meta["owner_class"] == "first-party-app"
    assert meta["workflow_name"] == "reasoning_apply_v1"


def test_registration_is_idempotent():
    from AINDY.runtime.nodus_workflow_registry import get_nodus_workflow

    # overwrite=True -> re-running boot registration does not raise.
    bootstrap._register_nodus_workflows()
    bootstrap._register_nodus_workflows()
    assert get_nodus_workflow("reasoning_apply_v1") is not None
