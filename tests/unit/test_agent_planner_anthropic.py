"""Unit tests for the app-owned Claude planner backend.

These mock the Anthropic client — no network, no API key. A live Claude call is
verified on Linux CI (this stack's authoritative oracle), not locally.
"""
from __future__ import annotations

import types

import pytest

from apps.agent.agents import planner_anthropic as pa

pytestmark = [pytest.mark.app_profile]


def _fake_message(plan: dict):
    """Build a fake Anthropic Message whose content carries a submit_plan tool_use."""
    tool_block = types.SimpleNamespace(type="tool_use", name="submit_plan", input=plan)
    return types.SimpleNamespace(content=[tool_block])


class _FakeClient:
    def __init__(self, message, capture: dict):
        self._message = message
        self._capture = capture
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self._capture.update(kwargs)
        return self._message


def _request(objective="Recall my priorities", tools=None, system_prompt="SYS"):
    from AINDY.agents.agent_runtime.planner_backends import PlannerRequest

    return PlannerRequest(
        objective=objective,
        run_type="default",
        user_id=None,
        system_prompt=system_prompt,
        tools=tuple(tools if tools is not None else [{"name": "memory.recall"}, {"name": "task.create"}]),
    )


def test_backend_parses_forced_tool_plan(monkeypatch):
    plan = {
        "executive_summary": "Recall priorities.",
        "steps": [{"tool": "memory.recall", "args": {"query": "priorities"},
                   "risk_level": "low", "description": "Recall."}],
        "overall_risk": "low",
    }
    capture: dict = {}
    monkeypatch.setattr(pa, "_make_client", lambda: _FakeClient(_fake_message(plan), capture))

    result = pa.claude_planner_backend(_request())

    assert result == plan
    # tool_choice is pinned to submit_plan; step tools are constrained to the catalog.
    assert capture["tool_choice"] == {"type": "tool", "name": "submit_plan"}
    enum = capture["tools"][0]["input_schema"]["properties"]["steps"]["items"]["properties"]["tool"]["enum"]
    assert set(enum) == {"memory.recall", "task.create"}
    assert capture["system"] == "SYS"


def test_backend_uses_default_model(monkeypatch):
    capture: dict = {}
    monkeypatch.delenv("AINDY_CLAUDE_PLANNER_MODEL", raising=False)
    monkeypatch.setattr(pa, "_make_client", lambda: _FakeClient(_fake_message({"steps": []}), capture))
    pa.claude_planner_backend(_request())
    assert capture["model"] == "claude-opus-4-8"


def test_backend_honors_model_override(monkeypatch):
    capture: dict = {}
    monkeypatch.setenv("AINDY_CLAUDE_PLANNER_MODEL", "claude-sonnet-4-6")
    monkeypatch.setattr(pa, "_make_client", lambda: _FakeClient(_fake_message({"steps": []}), capture))
    pa.claude_planner_backend(_request())
    assert capture["model"] == "claude-sonnet-4-6"


def test_backend_requires_tools(monkeypatch):
    monkeypatch.setattr(pa, "_make_client", lambda: pytest.fail("client should not be built"))
    with pytest.raises(pa.AnthropicPlannerError):
        pa.claude_planner_backend(_request(tools=[]))


def test_backend_raises_when_no_tool_use_block(monkeypatch):
    empty = types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="nope")])
    monkeypatch.setattr(pa, "_make_client", lambda: _FakeClient(empty, {}))
    with pytest.raises(pa.AnthropicPlannerError):
        pa.claude_planner_backend(_request())


def test_backend_registers_as_anthropic_chat(client):
    """After app bootstrap, the backend is selectable by name."""
    from AINDY.platform_layer.registry import get_agent_planner_backend

    assert get_agent_planner_backend("anthropic_chat") is pa.claude_planner_backend
