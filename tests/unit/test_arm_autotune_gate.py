"""
Unit tests for the ARM auto-tune safety gate (pure function, no DB).

The gate decides which of the suggestion engine's ``auto_apply_safe`` changes may be
auto-applied. Each rule is exercised in isolation.
"""
from __future__ import annotations

import pytest

from apps.arm.services.arm_autotune_service import (
    AUTO_TUNE_ALLOWED_KEYS,
    MAX_CHANGES_PER_RUN,
    MIN_SESSIONS,
    evaluate_autotune_gate,
)

pytestmark = pytest.mark.app_profile


def _bundle(*changes: dict) -> dict:
    """Wrap raw config_change dicts as low-risk auto_apply_safe suggestions."""
    return {
        "auto_apply_safe": [
            {
                "metric": c.get("_metric", "decision_efficiency"),
                "risk": c.get("_risk", "low"),
                "suggestion": "tune",
                "config_change": {k: v for k, v in c.items() if not k.startswith("_")},
            }
            for c in changes
        ]
    }


_ENOUGH = {"total_sessions": 10}


def test_applies_low_risk_whitelisted_change():
    bundle = _bundle({"temperature": 0.1})
    applied, skipped = evaluate_autotune_gate(bundle, {"temperature": 0.2}, _ENOUGH)
    assert len(applied) == 1
    assert applied[0]["param"] == "temperature"
    assert applied[0]["old"] == 0.2
    assert applied[0]["new"] == 0.1
    assert applied[0]["risk"] == "low"
    assert skipped == []


def test_min_sessions_blocks_everything():
    bundle = _bundle({"temperature": 0.1})
    applied, skipped = evaluate_autotune_gate(
        bundle, {"temperature": 0.2}, {"total_sessions": MIN_SESSIONS - 1}
    )
    assert applied == []
    assert skipped and "insufficient sessions" in skipped[0]["reason"]


def test_non_whitelisted_key_is_skipped():
    # A model swap must never auto-apply even if mislabeled low risk.
    bundle = _bundle({"analysis_model": "gpt-4o-mini"})
    applied, skipped = evaluate_autotune_gate(bundle, {"analysis_model": "gpt-4o"}, _ENOUGH)
    assert applied == []
    assert skipped[0]["param"] == "analysis_model"
    assert "whitelist" in skipped[0]["reason"]
    assert "analysis_model" not in AUTO_TUNE_ALLOWED_KEYS


def test_cooldown_key_is_skipped():
    bundle = _bundle({"temperature": 0.1})
    applied, skipped = evaluate_autotune_gate(
        bundle, {"temperature": 0.2}, _ENOUGH, recently_changed_keys={"temperature"}
    )
    assert applied == []
    assert "cooldown" in skipped[0]["reason"]


def test_value_is_clamped_to_bounds():
    # Suggestion pushes temperature absurdly low / retry absurdly high — both clamp.
    bundle = _bundle({"temperature": -5}, {"retry_limit": 99})
    applied, _ = evaluate_autotune_gate(
        bundle, {"temperature": 0.2, "retry_limit": 3}, _ENOUGH
    )
    by_param = {c["param"]: c["new"] for c in applied}
    assert by_param["temperature"] == 0.1   # lower bound
    assert by_param["retry_limit"] == 5     # upper bound


def test_no_op_change_is_skipped():
    bundle = _bundle({"temperature": 0.2})
    applied, skipped = evaluate_autotune_gate(bundle, {"temperature": 0.2}, _ENOUGH)
    assert applied == []
    assert "no-op" in skipped[0]["reason"]


def test_max_changes_per_run_enforced():
    changes = [
        {"temperature": 0.1},
        {"retry_limit": 4},
        {"max_output_tokens": 1500},
        {"max_file_size_bytes": 80000},
    ]
    current = {
        "temperature": 0.2,
        "retry_limit": 3,
        "max_output_tokens": 2000,
        "max_file_size_bytes": 100000,
    }
    applied, skipped = evaluate_autotune_gate(_bundle(*changes), current, _ENOUGH)
    assert len(applied) == MAX_CHANGES_PER_RUN
    assert any("exceeds max" in s["reason"] for s in skipped)


def test_non_low_risk_candidate_is_ignored():
    # Defense-in-depth: a medium-risk item that slipped into auto_apply_safe.
    bundle = _bundle({"temperature": 0.1, "_risk": "medium"})
    applied, _ = evaluate_autotune_gate(bundle, {"temperature": 0.2}, _ENOUGH)
    assert applied == []
