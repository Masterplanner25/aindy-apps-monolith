"""The app defaults agent execution to `nodus_vm` on real boots, never under test.

`apps/agent/bootstrap.py::_select_execution_backend` opts every real deployment into the
`nodus_vm` agent-execution backend (RTR-1 §5, validated by
`tests/integration/test_nodus_vm.py`). It MUST stay a no-op under test: the integration
harness runs no scheduler heartbeat, so a parked/deferred nodus_vm continuation would never
complete — flipping the default there would hang the agent suite. These tests lock that
gate in place. See TECH_DEBT RTR-1-NODUS-COMPLETION.
"""
from __future__ import annotations

import os

import pytest

from apps.agent.bootstrap import _select_execution_backend

pytestmark = pytest.mark.app_profile

BACKEND_ENV = "AINDY_AGENT_EXECUTION_BACKEND"


def _force_is_testing(monkeypatch, value: bool) -> None:
    from AINDY.config import settings

    # is_testing is a read-only property; replace it on the class (monkeypatch restores it).
    monkeypatch.setattr(type(settings), "is_testing", property(lambda self: value))


def test_backend_not_flipped_under_testing(monkeypatch):
    # The critical guard: under test the app must NOT set nodus_vm.
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    _force_is_testing(monkeypatch, True)

    _select_execution_backend()

    assert BACKEND_ENV not in os.environ, (
        "the app flipped agent execution to nodus_vm under test — the harness runs no "
        "scheduler heartbeat, so nodus_vm runs would never complete and the agent suite "
        "would hang"
    )


def test_defaults_to_nodus_vm_on_real_boot(monkeypatch):
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    _force_is_testing(monkeypatch, False)

    _select_execution_backend()

    assert os.environ.get(BACKEND_ENV) == "nodus_vm"


def test_explicit_backend_override_wins(monkeypatch):
    # setdefault must not clobber an explicit ops/CI value.
    monkeypatch.setenv(BACKEND_ENV, "agent_flow")
    _force_is_testing(monkeypatch, False)

    _select_execution_backend()

    assert os.environ.get(BACKEND_ENV) == "agent_flow"
