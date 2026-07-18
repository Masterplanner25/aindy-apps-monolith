"""Identity inference — evidence model (rules -> probabilistic).

Covers the shift from single-observation rule-flips to confidence-weighted evidence:
the aggregation + confidence math, the commit gates (confidence floor, min support,
switch margin/hysteresis), recency decay, and the rewired ``IdentityService.observe``
that records signals and only commits a dimension when the evidence is confident.

Runs on the SQLite app-profile harness.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.identity.models.identity_signal import IdentitySignal
from apps.identity.services import identity_inference_service as inference
from apps.identity.services.identity_service import IdentityService

pytestmark = pytest.mark.app_profile


def _uid() -> str:
    return str(uuid.uuid4())


class TestAggregationAndInference:

    def test_empty_inference(self, db_session):
        v = inference.infer_dimension(db_session, _uid(), "risk_tolerance")
        assert v["value"] is None
        assert v["committable"] is False
        assert v["support"] == 0.0

    def test_aggregate_sums_weight_per_value(self, db_session):
        uid = _uid()
        inference.record_signal(db_session, uid, "risk_tolerance", "aggressive", weight=1.5)
        inference.record_signal(db_session, uid, "risk_tolerance", "aggressive", weight=1.5)
        inference.record_signal(db_session, uid, "risk_tolerance", "conservative", weight=1.0)
        totals = inference.aggregate(db_session, uid, "risk_tolerance")
        assert totals["aggressive"] == pytest.approx(3.0, abs=0.05)
        assert totals["conservative"] == pytest.approx(1.0, abs=0.05)

    def test_confidence_is_leading_share(self, db_session):
        uid = _uid()
        inference.record_signal(db_session, uid, "speed_vs_quality", "quality", weight=3.0)
        inference.record_signal(db_session, uid, "speed_vs_quality", "speed", weight=1.0)
        v = inference.infer_dimension(db_session, uid, "speed_vs_quality")
        assert v["value"] == "quality"
        assert v["confidence"] == pytest.approx(0.75, abs=0.02)
        assert v["committable"] is True  # 0.75 >= 0.6 and support 4 >= 2

    def test_below_confidence_floor_not_committable(self, db_session):
        uid = _uid()
        # near-tie -> confidence ~0.55 < 0.6
        inference.record_signal(db_session, uid, "risk_tolerance", "aggressive", weight=1.1)
        inference.record_signal(db_session, uid, "risk_tolerance", "moderate", weight=0.9)
        v = inference.infer_dimension(db_session, uid, "risk_tolerance")
        assert v["committable"] is False

    def test_below_min_support_not_committable(self, db_session):
        uid = _uid()
        # confident (100%) but only 1.0 total support < MIN_SUPPORT (2.0)
        inference.record_signal(db_session, uid, "risk_tolerance", "aggressive", weight=1.0)
        v = inference.infer_dimension(db_session, uid, "risk_tolerance")
        assert v["confidence"] == pytest.approx(1.0)
        assert v["support"] == pytest.approx(1.0)
        assert v["committable"] is False

    def test_hysteresis_blocks_marginal_switch(self, db_session):
        uid = _uid()
        # leader clears the floor on its own, but only marginally beats the current value
        inference.record_signal(db_session, uid, "risk_tolerance", "aggressive", weight=3.1)
        inference.record_signal(db_session, uid, "risk_tolerance", "moderate", weight=1.9)
        # confidence(aggressive)=0.62 >= 0.6, but current=moderate share=0.38;
        # 0.62 - 0.38 = 0.24 >= 0.15 -> would switch. Tighten to a true marginal case:
        db_session.query(IdentitySignal).filter(IdentitySignal.user_id == uuid.UUID(uid)).delete()
        inference.record_signal(db_session, uid, "risk_tolerance", "aggressive", weight=2.15)
        inference.record_signal(db_session, uid, "risk_tolerance", "moderate", weight=1.85)
        v = inference.infer_dimension(db_session, uid, "risk_tolerance", current="moderate")
        # aggressive share ~0.538; margin vs moderate(0.462) ~0.076 < 0.15 -> no switch
        assert v["value"] == "aggressive"
        assert v["committable"] is False

    def test_sustained_counter_evidence_switches(self, db_session):
        uid = _uid()
        for _ in range(5):
            inference.record_signal(db_session, uid, "speed_vs_quality", "speed", weight=1.0)
        inference.record_signal(db_session, uid, "speed_vs_quality", "quality", weight=1.0)
        v = inference.infer_dimension(db_session, uid, "speed_vs_quality", current="quality")
        assert v["value"] == "speed"
        assert v["committable"] is True  # decisive lead overcomes the current value

    def test_same_as_current_not_committable(self, db_session):
        uid = _uid()
        inference.record_signal(db_session, uid, "risk_tolerance", "aggressive", weight=3.0)
        v = inference.infer_dimension(db_session, uid, "risk_tolerance", current="aggressive")
        assert v["value"] == "aggressive"
        assert v["committable"] is False  # already reflects the leader

    def test_recency_decay_downweights_old_evidence(self, db_session):
        uid = _uid()
        old = datetime.now(timezone.utc) - timedelta(days=120)  # ~4 half-lives -> ~1/16
        db_session.add(IdentitySignal(
            user_id=uuid.UUID(uid), dimension="speed_vs_quality", value="speed",
            weight=3.0, created_at=old,
        ))
        db_session.flush()
        inference.record_signal(db_session, uid, "speed_vs_quality", "quality", weight=1.0)
        # fresh quality (1.0) outweighs decayed speed (3.0 * ~0.0625 ~= 0.19)
        v = inference.infer_dimension(db_session, uid, "speed_vs_quality")
        assert v["value"] == "quality"

    def test_infer_ranked_orders_and_gates_by_support(self, db_session):
        uid = _uid()
        for _ in range(3):
            inference.record_signal(db_session, uid, "language", "python", weight=1.0)
        for _ in range(2):
            inference.record_signal(db_session, uid, "language", "rust", weight=1.0)
        inference.record_signal(db_session, uid, "language", "cobol", weight=1.0)  # one-off, below support
        ranked = inference.infer_ranked(db_session, uid, "language")
        assert ranked == ["python", "rust"]  # cobol (1.0 < 2.0) excluded, ordered by weight
