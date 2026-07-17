"""
Unit tests for the Revenue Intelligence pricing gate (pure function, no DB).

Deterministic price recommendations from realized outcomes. Each rule in isolation.
"""
from __future__ import annotations

import pytest

from apps.freelance.services.revenue_intelligence_service import (
    MULT_MAX,
    MULT_MIN,
    evaluate_pricing_gate,
)

pytestmark = pytest.mark.app_profile


def _stats(sample=5, baseline=100.0, avg_rating=4.5, refund_rate=0.0, acceptance=0.9):
    return {
        "sample_size": sample,
        "baseline_price": baseline,
        "avg_rating": avg_rating,
        "refund_rate": refund_rate,
        "acceptance_rate": acceptance,
        "realized_revenue": (baseline or 0) * sample,
        "total_orders": sample,
    }


def test_high_rating_recommends_increase():
    recs, skipped = evaluate_pricing_gate({"web": _stats(avg_rating=4.5, refund_rate=0.0)}, {}, set())
    assert len(recs) == 1
    r = recs[0]
    assert r["direction"] == "increase"
    assert r["recommended_price"] > r["baseline_price"]
    assert MULT_MIN <= r["multiplier"] <= MULT_MAX


def test_low_rating_recommends_decrease():
    recs, _ = evaluate_pricing_gate({"web": _stats(avg_rating=2.0, refund_rate=0.3)}, {}, set())
    assert recs[0]["direction"] == "decrease"
    assert recs[0]["recommended_price"] < recs[0]["baseline_price"]


def test_neutral_signals_hold_is_skipped():
    # rating 3.5 (no branch), refund 8%, acceptance 70% -> multiplier stays 1.0 -> hold
    recs, skipped = evaluate_pricing_gate(
        {"web": _stats(avg_rating=3.5, refund_rate=0.08, acceptance=0.7)}, {}, set()
    )
    assert recs == []
    assert any("hold" in s["reason"] for s in skipped)


def test_insufficient_sample_skipped():
    recs, skipped = evaluate_pricing_gate({"web": _stats(sample=2)}, {}, set())
    assert recs == []
    assert "insufficient sample" in skipped[0]["reason"]


def test_cooldown_skipped():
    recs, skipped = evaluate_pricing_gate({"web": _stats()}, {}, {"web"})
    assert recs == []
    assert "cooldown" in skipped[0]["reason"]


def test_no_baseline_price_skipped():
    stats = _stats()
    stats["baseline_price"] = None
    recs, skipped = evaluate_pricing_gate({"web": stats}, {}, set())
    assert recs == []
    assert "baseline" in skipped[0]["reason"]


def test_current_price_overrides_historical_baseline():
    stats = _stats(baseline=None, avg_rating=4.5)  # no historical baseline
    recs, _ = evaluate_pricing_gate({"web": stats}, {"web": 200.0}, set())
    assert recs[0]["baseline_price"] == 200.0
    assert recs[0]["recommended_price"] > 200.0


def test_multiplier_is_bounded():
    recs, _ = evaluate_pricing_gate(
        {"web": _stats(avg_rating=5.0, refund_rate=0.0, acceptance=1.0)}, {}, set()
    )
    assert recs[0]["multiplier"] <= MULT_MAX


def test_low_acceptance_pulls_price_down():
    # Strong ratings but heavy price resistance nets to a decrease.
    recs, skipped = evaluate_pricing_gate(
        {"web": _stats(avg_rating=2.4, refund_rate=0.1, acceptance=0.2)}, {}, set()
    )
    assert recs and recs[0]["direction"] == "decrease"
