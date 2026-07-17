"""ARM capability definitions."""

from __future__ import annotations


def register() -> None:
    from AINDY.platform_layer.registry import register_capability_definition, register_tool_capabilities

    register_capability_definition(
        "external_api_call",
        {
            "description": "Call an external LLM or web-backed integration.",
            "risk_level": "medium",
        },
    )
    register_capability_definition(
        "self_tune",
        {
            "description": "Apply gated, reversible ARM self-tuning config changes (no egress).",
            "risk_level": "low",
        },
    )
    register_tool_capabilities("arm.analyze", ["external_api_call"])
    register_tool_capabilities("arm.generate", ["external_api_call"])
    register_tool_capabilities("arm.autotune", ["self_tune"])
