"""Freelance capability definitions."""

from __future__ import annotations


def register() -> None:
    from AINDY.platform_layer.registry import (
        register_capability_definition,
        register_tool_capabilities,
    )

    register_capability_definition(
        "revenue_optimize",
        {
            "description": (
                "Recommend/apply gated, revertible freelance service-price adjustments — "
                "an internal default price for future quotes only; no egress, no customer charge."
            ),
            "risk_level": "medium",
        },
    )
    register_capability_definition(
        "revenue_read",
        {
            "description": "Read freelance realized-revenue performance signals.",
            "risk_level": "low",
        },
    )
    register_tool_capabilities("freelance.optimize_pricing", ["revenue_optimize"])
    register_tool_capabilities("freelance.performance", ["revenue_read"])
