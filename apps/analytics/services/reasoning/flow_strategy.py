"""Reasoning flow strategy (ARM/Reasoning Phase 4).

Registers a flow strategy for the ``reasoning`` flow_type so a reasoning outcome
can execute through the runtime's standard intent-execution path
(`execute_intent({"workflow_type": "reasoning"})`) — entirely via the runtime's
`register_flow_strategy` surface, no runtime edits. The strategy resolves to the
single-node ``reasoning_apply`` flow, which computes and records the reasoning
recommendation (durable traceability through the flow engine).
"""

from __future__ import annotations

from typing import Any

# Flow definition (node-graph) the runtime executes for the "reasoning" intent.
_REASONING_FLOW: dict[str, Any] = {
    "start": "reasoning_apply_node",
    "edges": {"reasoning_apply_node": []},
    "end": ["reasoning_apply_node"],
}


def select_reasoning_flow(context: dict[str, Any]) -> dict[str, Any]:
    """Return the executable flow for a reasoning intent. ``context`` carries
    ``flow_type``/``intent_type``/``db``/``user_id`` (runtime-provided)."""
    return dict(_REASONING_FLOW)
