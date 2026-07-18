"""
Freelance agent tools dispatch to the right freelance syscall + capability
(Phase 2 — agent-driven execution). Hermetic: the syscall invocation is mocked.
"""
from __future__ import annotations

import pytest

import apps.freelance.agents.tools as ft

pytestmark = pytest.mark.app_profile


def test_optimize_pricing_dispatches_to_pricing_syscall(monkeypatch):
    captured = {}

    def _fake(syscall_name, args, *, user_id, capability):
        captured.update(name=syscall_name, args=args, user_id=user_id, capability=capability)
        return {
            "status": "applied",
            "applied": [{"service_type": "web", "recommended_price": 250.0}],
            "recommendations": [],
            "skipped": [],
            "dry_run": False,
            "would_change": True,
        }

    monkeypatch.setattr(ft, "invoke_tool_syscall", _fake)

    out = ft.freelance_optimize_pricing({"apply": True}, "u1", None)

    assert captured["name"] == "sys.v1.freelance.optimize_pricing"
    assert captured["capability"] == "freelance.optimize"
    assert captured["args"] == {"apply": True}
    assert captured["user_id"] == "u1"
    assert out["status"] == "applied"
    assert out["applied"] == [{"service_type": "web", "recommended_price": 250.0}]
    assert out["dry_run"] is False


def test_optimize_pricing_defaults_are_dry_run_shaped(monkeypatch):
    monkeypatch.setattr(
        ft, "invoke_tool_syscall",
        lambda name, args, *, user_id, capability: {"dry_run": True, "recommendations": [], "skipped": [], "would_change": False},
    )
    out = ft.freelance_optimize_pricing({}, "u1", None)
    assert out["dry_run"] is True
    assert out["would_change"] is False
    assert out["recommendations"] == []


def test_performance_dispatches_to_read_syscall(monkeypatch):
    captured = {}

    def _fake(syscall_name, args, *, user_id, capability):
        captured.update(name=syscall_name, capability=capability)
        return {"signals": [{"reason": "realized_revenue", "realized_revenue": 999.0}], "count": 1}

    monkeypatch.setattr(ft, "invoke_tool_syscall", _fake)

    out = ft.freelance_performance({}, "u1", None)

    assert captured["name"] == "sys.v1.freelance.get_performance_signals"
    assert captured["capability"] == "freelance.read"
    assert out["count"] == 1
    assert out["signals"][0]["reason"] == "realized_revenue"
