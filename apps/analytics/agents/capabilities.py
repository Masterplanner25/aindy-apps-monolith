"""Capability wiring for the reasoning agent tool.

Defines the ``read_reasoning`` capability and maps it to ``reasoning.evaluate``.
Both are required: without the tool->capability mapping (and a matching
definition), `get_plan_required_capabilities` returns empty and any plan using
the tool fails auto-approval. No agent-grant change is needed — the runtime adds
a tool's capabilities to the capability token per plan.
"""

from __future__ import annotations


def register() -> None:
    from AINDY.platform_layer.registry import (
        register_capability_definition,
        register_tool_capabilities,
    )

    register_capability_definition(
        "read_reasoning",
        {
            "description": "Read autonomous-reasoning recommendations (read-only).",
            "risk_level": "low",
        },
    )
    register_tool_capabilities("reasoning.evaluate", ["read_reasoning"])
