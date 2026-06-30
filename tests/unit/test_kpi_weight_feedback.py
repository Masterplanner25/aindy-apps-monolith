"""Explicit feedback -> KPI weight adaptation (Support System Step 5).

`adapt_kpi_weights` previously learned only from prediction accuracy. This covers
the new path where explicit `UserFeedback` (tied to a decision via
`loop_adjustment_id`) nudges the same KPI weights that decision maps to — while
remaining behavior-preserving when there is no feedback, and defensive when the
feedback read fails.

Runs on the SQLite app-profile harness (real `UserKpiWeights` row); the
dependency-adapter reads are monkeypatched.
"""

from __future__ import annotations

import uuid

import pytest

import apps.analytics.services.integration.dependency_adapter as adapter
from apps.analytics.services.scoring import kpi_weight_service as kws
from apps.analytics.user_score import KPI_WEIGHTS, KPI_WEIGHT_MIN_SAMPLES

pytestmark = pytest.mark.app_profile


def _adjustments(decision_type="reprioritize_tasks", accuracy=55, adjustment_id="adj-1"):
    # neutral accuracy (55) -> no accuracy nudge, isolating the feedback signal.
    row = {"id": adjustment_id, "decision_type": decision_type, "prediction_accuracy": accuracy}
    return [dict(row) for _ in range(max(KPI_WEIGHT_MIN_SAMPLES, 1))]


def test_positive_feedback_boosts_decision_kpis(db_session, monkeypatch):
    monkeypatch.setattr(adapter, "list_strategy_accuracy_adjustments", lambda **kw: _adjustments())
    monkeypatch.setattr(
        adapter, "list_recent_feedback_rows",
        lambda **kw: [{"loop_adjustment_id": "adj-1", "feedback_value": 1}],
    )

    result = kws.adapt_kpi_weights(db_session, str(uuid.uuid4()))

    assert result["status"] == "adapted"
    assert result["feedback_nudges_applied"] == 2  # reprioritize_tasks -> 2 KPIs
    w = result["weights"]
    # the decision's KPIs rise vs default; non-nudged KPI falls under normalization
    assert w["execution_speed"] > KPI_WEIGHTS["execution_speed"]
    assert w["decision_efficiency"] > KPI_WEIGHTS["decision_efficiency"]
    assert w["focus_quality"] < KPI_WEIGHTS["focus_quality"]
    assert abs(sum(w.values()) - 1.0) < 1e-6  # stays normalized


def test_negative_feedback_reduces_decision_kpis(db_session, monkeypatch):
    monkeypatch.setattr(adapter, "list_strategy_accuracy_adjustments", lambda **kw: _adjustments())
    monkeypatch.setattr(
        adapter, "list_recent_feedback_rows",
        lambda **kw: [{"loop_adjustment_id": "adj-1", "feedback_value": -1}],
    )

    result = kws.adapt_kpi_weights(db_session, str(uuid.uuid4()))

    assert result["status"] == "adapted"
    assert result["feedback_nudges_applied"] == 2
    w = result["weights"]
    assert w["execution_speed"] < KPI_WEIGHTS["execution_speed"]
    assert w["focus_quality"] > KPI_WEIGHTS["focus_quality"]


def test_no_feedback_is_accuracy_only(db_session, monkeypatch):
    # high accuracy drives the (unchanged) accuracy path; no feedback present.
    monkeypatch.setattr(adapter, "list_strategy_accuracy_adjustments", lambda **kw: _adjustments(accuracy=85))
    monkeypatch.setattr(adapter, "list_recent_feedback_rows", lambda **kw: [])

    result = kws.adapt_kpi_weights(db_session, str(uuid.uuid4()))

    assert result["status"] == "adapted"
    assert result["feedback_nudges_applied"] == 0
    # accuracy alone still boosts the decision's KPIs
    assert result["weights"]["execution_speed"] > KPI_WEIGHTS["execution_speed"]


def test_feedback_read_failure_is_non_fatal(db_session, monkeypatch):
    monkeypatch.setattr(adapter, "list_strategy_accuracy_adjustments", lambda **kw: _adjustments(accuracy=85))

    def _boom(**kw):
        raise RuntimeError("feedback store down")

    monkeypatch.setattr(adapter, "list_recent_feedback_rows", _boom)

    result = kws.adapt_kpi_weights(db_session, str(uuid.uuid4()))

    # accuracy adaptation still succeeds; feedback failure is swallowed
    assert result["status"] == "adapted"
    assert result["feedback_nudges_applied"] == 0


def test_unmappable_feedback_is_ignored(db_session, monkeypatch):
    # neutral accuracy (no accuracy nudge) + feedback whose adjustment id is unknown
    monkeypatch.setattr(adapter, "list_strategy_accuracy_adjustments", lambda **kw: _adjustments())
    monkeypatch.setattr(
        adapter, "list_recent_feedback_rows",
        lambda **kw: [{"loop_adjustment_id": "does-not-exist", "feedback_value": 1}],
    )

    result = kws.adapt_kpi_weights(db_session, str(uuid.uuid4()))

    # nothing to apply -> no adaptation (unchanged behavior)
    assert result["status"] == "skipped"
    assert result["reason"] == "no_nudges"
