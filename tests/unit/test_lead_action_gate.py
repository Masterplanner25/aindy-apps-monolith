"""
Unit tests for the Search Execution Layer gate (pure function, no DB).

Decides which scored leads warrant an outreach action. Each rule in isolation.
"""
from __future__ import annotations

import pytest

from apps.search.services.lead_execution_service import (
    MAX_ACTIONS_PER_RUN,
    evaluate_lead_action_gate,
)

pytestmark = pytest.mark.app_profile


def _lead(lead_id: int, score: float, dq=90) -> dict:
    return {
        "id": lead_id,
        "company": f"Co{lead_id}",
        "url": "https://example.com",
        "context": "context",
        "overall_score": score,
        "data_quality_score": dq,
    }


def test_selects_qualified_lead():
    selected, skipped = evaluate_lead_action_gate([_lead(1, 80)], set())
    assert len(selected) == 1
    assert selected[0]["lead_id"] == 1
    assert selected[0]["score"] == 80
    assert skipped == []


def test_below_score_threshold_skipped():
    selected, skipped = evaluate_lead_action_gate([_lead(1, 40)], set())
    assert selected == []
    assert "below score threshold" in skipped[0]["reason"]


def test_low_data_quality_skipped():
    selected, skipped = evaluate_lead_action_gate([_lead(1, 80, dq=10)], set())
    assert selected == []
    assert "insufficient data quality" in skipped[0]["reason"]


def test_missing_data_quality_is_allowed():
    selected, _ = evaluate_lead_action_gate([_lead(1, 80, dq=None)], set())
    assert len(selected) == 1


def test_already_actioned_is_skipped():
    selected, skipped = evaluate_lead_action_gate([_lead(1, 80)], {1})
    assert selected == []
    assert "already actioned" in skipped[0]["reason"]


def test_max_per_run_keeps_highest_scoring():
    leads = [_lead(i, 60 + i) for i in range(1, 10)]  # scores 61..69
    selected, skipped = evaluate_lead_action_gate(leads, set())
    assert len(selected) == MAX_ACTIONS_PER_RUN
    kept = {s["lead_id"] for s in selected}
    assert kept == {5, 6, 7, 8, 9}  # top 5 by score
    assert any("exceeds max" in s["reason"] for s in skipped)
