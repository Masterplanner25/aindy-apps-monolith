"""
Freelance Revenue Intelligence — feedback + revenue -> pricing.

Freelance recorded orders, feedback, and revenue but never fed any of it back into
pricing: prices were caller-supplied and the "AI summary" was a hardcoded template.
This service is the missing economic-intelligence half — the third instance of the
compute->consume gap (after ARM auto-tune and Search's Execution Layer), built on
the same guarded-consumer template.

For each service type it reads the realized outcomes (paid revenue, acceptance,
refund rate, client ratings) and recommends a *bounded* price adjustment. Applying a
recommendation writes the studio's own default price for that service type
(``ServicePrice``) — an internal default for future quotes. It never changes an
existing order and never charges a customer. Every applied run is revertible.

The gate (``evaluate_pricing_gate``) is a pure, deterministic function — no LLM, no
DB — so the pricing logic is explainable and unit-testable.

Gate rules (all must pass for a service type to get a recommendation):
  * min sample  — need at least MIN_SAMPLE_SIZE paid orders (don't tune on noise)
  * cooldown    — a service priced recently is left alone
  * baseline    — a positive baseline price must exist
  * signal      — the bounded multiplier must move the price (neutral -> hold/skip)
"""
from __future__ import annotations

import logging
import statistics
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import require_user_id
from apps.freelance.models.freelance import ClientFeedback, FreelanceOrder
from apps.freelance.models.pricing import PricingRecommendation, ServicePrice

logger = logging.getLogger(__name__)


# ── Gate policy ───────────────────────────────────────────────────────────────

MIN_SAMPLE_SIZE = 3          # paid orders for a service type before we tune it
MULT_MIN = 0.85              # never cut more than 15% in one run
MULT_MAX = 1.20              # never raise more than 20% in one run
HOLD_DEADBAND = 0.02         # |multiplier - 1| within this => hold (no-op)
COOLDOWN_HOURS = 24

# ── Learning close: judge on REALIZED revenue, then learn ──────────────────────
# A price change is judged on expected revenue per lead (price × acceptance) — the
# objective the static rule ignored. Improved/degraded is a *relative* move so it is
# scale-invariant across services. A degraded change is auto-reverted; the verdict feeds a
# learned per-service revenue-direction bias that nudges the (previously static) multiplier.
OBSERVATION_HOURS = 72       # give a price change time to attract/convert orders before judging
REL_DELTA = 0.05             # ±5% move in revenue_score classifies improved / degraded
LEARN_WEIGHT = 0.08          # how much the learned revenue-direction moves the multiplier
LEARN_MIN_OUTCOMES = 2       # need this many judged outcomes before trusting the learned bias

# (direction, outcome) -> which way the service's price should lean.
# increase+improved => raising helped => under-priced (+); increase+degraded => over-priced (−);
# decrease+improved => lowering helped => over-priced (−); decrease+degraded => under-priced (+).
_DIRECTION_OUTCOME_SIGN: dict[tuple[str, str], int] = {
    ("increase", "improved"): +1,
    ("increase", "degraded"): -1,
    ("decrease", "improved"): -1,
    ("decrease", "degraded"): +1,
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _revenue_score(stats: dict) -> float:
    """Expected revenue per lead = price × acceptance — the objective a price change is judged on.

    Captures the elasticity tradeoff the static rule missed: raising the price lifts the price
    term but may lower acceptance, so only the *product* says whether revenue actually improved.
    """
    price = float((stats or {}).get("baseline_price") or 0.0)
    acceptance = float((stats or {}).get("acceptance_rate") or 0.0)
    return round(price * acceptance, 4)


def _classify_outcome(prior_score: float, current_score: float) -> tuple[str, float]:
    """Relative change in revenue_score -> (outcome, relative_delta)."""
    denom = prior_score if prior_score > 1e-9 else 1e-9
    rel = round((current_score - prior_score) / denom, 4)
    if rel >= REL_DELTA:
        return "improved", rel
    if rel <= -REL_DELTA:
        return "degraded", rel
    return "neutral", rel


def learned_revenue_bias(outcomes: list[tuple[str, str]]) -> float:
    """Per-service revenue-direction bias in [-1, 1] learned from past (direction, outcome) pairs.

    Positive => history says this service is under-priced (lean up); negative => over-priced.
    Returns 0.0 until at least LEARN_MIN_OUTCOMES judged (improved/degraded) outcomes exist.
    """
    signs = [
        _DIRECTION_OUTCOME_SIGN[(d, o)]
        for (d, o) in outcomes
        if (d, o) in _DIRECTION_OUTCOME_SIGN
    ]
    if len(signs) < LEARN_MIN_OUTCOMES:
        return 0.0
    return round(sum(signs) / len(signs), 3)


def get_service_price(db: Session, user_id, service_type: str) -> float | None:
    """The studio's current default price for a service type, or None if unset.

    The read seam for the loop: order intake / quoting can default a new order's
    price from here when none is supplied. Exposed as a plain accessor (freelance
    is a leaf domain — its own intake is the consumer).
    """
    try:
        uid = uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return None
    row = (
        db.query(ServicePrice)
        .filter(ServicePrice.user_id == uid, ServicePrice.service_type == service_type)
        .first()
    )
    return row.current_price if row else None


def _price_multiplier(stats: dict, learned_bias: float = 0.0) -> float:
    """Explainable multiplier from realized outcomes, nudged by the learned revenue direction.

    The satisfaction terms (rating/refund/acceptance) are the prior; ``learned_bias`` — the
    per-service revenue-direction learned from how past changes moved realized revenue — is the
    correction that makes the loop optimize revenue, not just satisfaction.
    """
    mult = 1.0
    avg_rating = stats.get("avg_rating")            # 1..5 or None
    refund_rate = stats.get("refund_rate") or 0.0
    acceptance_rate = stats.get("acceptance_rate")

    if avg_rating is not None:
        if avg_rating >= 4.3 and refund_rate <= 0.05:
            mult += 0.12                            # loved + rarely refunded -> raise
        elif avg_rating >= 3.8 and refund_rate <= 0.10:
            mult += 0.06
        elif avg_rating <= 2.5 or refund_rate >= 0.25:
            mult -= 0.10                            # weak reception -> lower
    elif refund_rate >= 0.25:
        mult -= 0.10

    if acceptance_rate is not None and acceptance_rate < 0.4:
        mult -= 0.05                                # price resistance -> lower

    # Learned revenue-direction correction (0 until enough judged outcomes exist).
    mult += LEARN_WEIGHT * _clamp(learned_bias, -1.0, 1.0)

    return round(_clamp(mult, MULT_MIN, MULT_MAX), 3)


def _rationale(stats: dict, direction: str) -> str:
    bits = []
    if stats.get("avg_rating") is not None:
        bits.append(f"avg rating {stats['avg_rating']:.1f}/5")
    bits.append(f"refund rate {(stats.get('refund_rate') or 0) * 100:.0f}%")
    if stats.get("acceptance_rate") is not None:
        bits.append(f"acceptance {(stats['acceptance_rate']) * 100:.0f}%")
    bits.append(f"n={stats.get('sample_size')}")
    verb = {"increase": "raise", "decrease": "lower", "hold": "hold"}[direction]
    return f"{verb} price — " + ", ".join(bits)


def evaluate_pricing_gate(
    stats_by_service: dict[str, dict],
    current_prices: dict[str, float],
    recently_changed: set | None = None,
    *,
    min_sample: int = MIN_SAMPLE_SIZE,
    learned_bias_by_service: dict[str, float] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Decide which service types warrant a price change. Pure: no I/O.
    Returns ``(recommendations, skipped)``.

    ``learned_bias_by_service`` — per-service revenue-direction learned from past outcomes;
    nudges the multiplier toward what historically improved realized revenue.
    """
    recently_changed = recently_changed or set()
    learned_bias_by_service = learned_bias_by_service or {}
    recommendations: list[dict] = []
    skipped: list[dict] = []

    for service_type in sorted(stats_by_service):
        stats = stats_by_service[service_type]
        sample_size = int(stats.get("sample_size") or 0)

        if sample_size < min_sample:
            skipped.append({"service_type": service_type, "reason": f"insufficient sample (n={sample_size} < {min_sample})"})
            continue
        if service_type in recently_changed:
            skipped.append({"service_type": service_type, "reason": f"cooldown: priced within {COOLDOWN_HOURS}h"})
            continue

        baseline = current_prices.get(service_type) or stats.get("baseline_price")
        if not baseline or baseline <= 0:
            skipped.append({"service_type": service_type, "reason": "no positive baseline price"})
            continue

        learned_bias = float(learned_bias_by_service.get(service_type, 0.0) or 0.0)
        mult = _price_multiplier(stats, learned_bias)
        if abs(mult - 1.0) <= HOLD_DEADBAND:
            skipped.append({"service_type": service_type, "reason": "signals neutral — hold"})
            continue

        recommended = round(baseline * mult, 2)
        if recommended == round(baseline, 2):
            skipped.append({"service_type": service_type, "reason": "no price change after rounding"})
            continue

        direction = "increase" if mult > 1.0 else "decrease"
        recommendations.append(
            {
                "service_type": service_type,
                "sample_size": sample_size,
                "baseline_price": round(baseline, 2),
                "recommended_price": recommended,
                "multiplier": mult,
                "direction": direction,
                "learned_bias": learned_bias,
                "rationale": _rationale(stats, direction),
                "signals": stats,
            }
        )

    return recommendations, skipped


# ── Service ───────────────────────────────────────────────────────────────────

class RevenueIntelligenceService:
    """Per-user consumer that turns realized outcomes into pricing decisions."""

    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = require_user_id(user_id)
        self.user_uuid = uuid.UUID(str(self.user_id))

    # ── reads ─────────────────────────────────────────────────────────────────

    def _stats_by_service(self) -> dict[str, dict]:
        orders = (
            self.db.query(FreelanceOrder)
            .filter(FreelanceOrder.user_id == self.user_uuid)
            .all()
        )
        if not orders:
            return {}

        order_ids = [o.id for o in orders]
        ratings_by_order: dict[int, list[int]] = {}
        if order_ids:
            for fb in (
                self.db.query(ClientFeedback)
                .filter(ClientFeedback.order_id.in_(order_ids))
                .all()
            ):
                if fb.rating is not None:
                    ratings_by_order.setdefault(fb.order_id, []).append(fb.rating)

        grouped: dict[str, list] = {}
        for order in orders:
            grouped.setdefault(order.service_type or "unspecified", []).append(order)

        stats: dict[str, dict] = {}
        for service_type, svc_orders in grouped.items():
            paid = [o for o in svc_orders if o.payment_confirmed_at is not None]
            refunded = [o for o in svc_orders if o.refunded_at is not None]
            paid_prices = [float(o.price) for o in paid if (o.price or 0) > 0]
            all_prices = [float(o.price) for o in svc_orders if (o.price or 0) > 0]
            ratings = [r for o in svc_orders for r in ratings_by_order.get(o.id, [])]

            baseline_source = paid_prices or all_prices
            stats[service_type] = {
                "sample_size": len(paid),
                "total_orders": len(svc_orders),
                "baseline_price": round(statistics.median(baseline_source), 2) if baseline_source else None,
                "realized_revenue": round(sum(paid_prices), 2),
                "acceptance_rate": round(len(paid) / len(svc_orders), 3) if svc_orders else None,
                "refund_rate": round(len(refunded) / len(paid), 3) if paid else 0.0,
                "avg_rating": round(statistics.mean(ratings), 2) if ratings else None,
            }
        return stats

    def _current_prices(self) -> dict[str, float]:
        rows = (
            self.db.query(ServicePrice)
            .filter(ServicePrice.user_id == self.user_uuid)
            .all()
        )
        return {row.service_type: row.current_price for row in rows}

    def _recently_changed(self) -> set:
        since = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)
        rows = (
            self.db.query(PricingRecommendation.service_type)
            .filter(
                PricingRecommendation.user_id == self.user_uuid,
                PricingRecommendation.status == "applied",
                PricingRecommendation.created_at >= since,
            )
            .all()
        )
        return {row[0] for row in rows}

    def _learned_bias_by_service(self) -> dict[str, float]:
        """Per-service revenue-direction bias learned from past (direction, outcome) pairs."""
        rows = (
            self.db.query(
                PricingRecommendation.service_type,
                PricingRecommendation.direction,
                PricingRecommendation.outcome,
            )
            .filter(
                PricingRecommendation.user_id == self.user_uuid,
                PricingRecommendation.outcome.isnot(None),
            )
            .order_by(PricingRecommendation.created_at.asc())
            .all()
        )
        by_service: dict[str, list[tuple[str, str]]] = {}
        for service_type, direction, outcome in rows:
            by_service.setdefault(service_type, []).append((direction or "", outcome or ""))
        return {svc: learned_revenue_bias(pairs) for svc, pairs in by_service.items()}

    def plan(self) -> dict:
        """Dry run: which service prices *would* change, and what's gated."""
        recommendations, skipped = evaluate_pricing_gate(
            self._stats_by_service(),
            self._current_prices(),
            self._recently_changed(),
            learned_bias_by_service=self._learned_bias_by_service(),
        )
        return {"recommendations": recommendations, "skipped": skipped, "would_change": bool(recommendations)}

    # ── writes ────────────────────────────────────────────────────────────────

    def evaluate_outcomes(self, observation_hours: int = OBSERVATION_HOURS) -> dict:
        """LEARN step: score each matured applied change on realized expected-revenue
        (price × acceptance) vs its apply-time snapshot, record the verdict, and AUTO-REVERT
        a change that degraded revenue. This is what makes *realized revenue* — not just
        satisfaction — the thing the loop optimizes, and it feeds the per-service learned bias."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=observation_hours)
        matured = (
            self.db.query(PricingRecommendation)
            .filter(
                PricingRecommendation.user_id == self.user_uuid,
                PricingRecommendation.status == "applied",
                PricingRecommendation.outcome.is_(None),
                PricingRecommendation.applied_at.isnot(None),
                PricingRecommendation.applied_at <= cutoff,
            )
            .order_by(PricingRecommendation.applied_at.asc())
            .all()
        )
        empty = {"evaluated": 0, "improved": 0, "degraded": 0, "neutral": 0, "auto_reverted": 0, "results": []}
        if not matured:
            return empty

        current_stats = self._stats_by_service()
        counts = {"improved": 0, "degraded": 0, "neutral": 0}
        auto_reverted = 0
        results: list[dict] = []
        for rec in matured:
            prior_score = _revenue_score(rec.signals or {})
            current_score = _revenue_score(current_stats.get(rec.service_type, {}))
            outcome, delta = _classify_outcome(prior_score, current_score)
            rec.outcome = outcome
            rec.outcome_delta = delta
            rec.outcome_snapshot = current_stats.get(rec.service_type, {})
            rec.evaluated_at = now
            self.db.commit()
            counts[outcome] += 1
            reverted = False
            if outcome == "degraded":
                reverted = self.revert(rec.id).get("status") == "reverted"
                if reverted:
                    auto_reverted += 1
            results.append({
                "recommendation_id": rec.id,
                "service_type": rec.service_type,
                "outcome": outcome,
                "delta": delta,
                "direction": rec.direction,
                "auto_reverted": reverted,
            })
        return {"evaluated": len(matured), **counts, "auto_reverted": auto_reverted, "results": results}

    def apply(self, trigger: str = "manual") -> dict:
        """Learn, then apply: first score matured past changes on realized revenue (auto-reverting
        the ones that hurt), then write the new gated recommendations (now nudged by what was learned)."""
        learning = self.evaluate_outcomes()
        proposal = self.plan()
        recommendations = proposal["recommendations"]

        if not recommendations:
            return {
                "status": "no_change",
                "dry_run": False,
                "applied": [],
                "skipped": proposal["skipped"],
                "count": 0,
                "learning": learning,
            }

        now = datetime.now(timezone.utc)
        applied = []
        for rec in recommendations:
            prior_price = self._upsert_service_price(rec["service_type"], rec["recommended_price"])
            row = PricingRecommendation(
                user_id=self.user_uuid,
                service_type=rec["service_type"],
                sample_size=rec["sample_size"],
                baseline_price=rec["baseline_price"],
                recommended_price=rec["recommended_price"],
                multiplier=rec["multiplier"],
                direction=rec["direction"],
                rationale=rec["rationale"],
                signals=rec["signals"],
                status="applied",
                prior_price=prior_price,
                trigger=trigger,
                applied_at=now,
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            applied.append(
                {
                    "recommendation_id": row.id,
                    "service_type": row.service_type,
                    "prior_price": prior_price,
                    "recommended_price": row.recommended_price,
                    "direction": row.direction,
                }
            )

        return {
            "status": "applied",
            "dry_run": False,
            "applied": applied,
            "skipped": proposal["skipped"],
            "count": len(applied),
            "learning": learning,
        }

    def revert(self, recommendation_id) -> dict:
        """Restore the price that was in effect before an applied recommendation."""
        try:
            rec_pk = int(recommendation_id)
        except (TypeError, ValueError):
            return {"status": "not_found", "recommendation_id": str(recommendation_id)}

        rec = (
            self.db.query(PricingRecommendation)
            .filter(PricingRecommendation.id == rec_pk, PricingRecommendation.user_id == self.user_uuid)
            .first()
        )
        if rec is None:
            return {"status": "not_found", "recommendation_id": rec_pk}
        if rec.status == "reverted":
            return {"status": "already_reverted", "recommendation_id": rec.id}

        row = self._get_service_price_row(rec.service_type)
        if rec.prior_price is None:
            # There was no default price before this run — remove the one we added.
            if row is not None:
                self.db.delete(row)
        elif row is not None:
            row.current_price = rec.prior_price
            row.source = "auto"

        rec.status = "reverted"
        rec.reverted_at = datetime.now(timezone.utc)
        self.db.commit()
        return {
            "status": "reverted",
            "recommendation_id": rec.id,
            "service_type": rec.service_type,
            "restored_price": rec.prior_price,
        }

    def history(self, limit: int = 20) -> list[dict]:
        rows = (
            self.db.query(PricingRecommendation)
            .filter(PricingRecommendation.user_id == self.user_uuid)
            .order_by(PricingRecommendation.created_at.desc(), PricingRecommendation.id.desc())
            .limit(limit)
            .all()
        )
        return [self._rec_to_dict(row) for row in rows]

    def catalog(self) -> list[dict]:
        rows = (
            self.db.query(ServicePrice)
            .filter(ServicePrice.user_id == self.user_uuid)
            .order_by(ServicePrice.service_type.asc())
            .all()
        )
        return [
            {
                "service_type": row.service_type,
                "current_price": row.current_price,
                "source": row.source,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]

    # ── helpers ─────────────────────────────────────────────────────────────────

    def _get_service_price_row(self, service_type: str) -> ServicePrice | None:
        return (
            self.db.query(ServicePrice)
            .filter(ServicePrice.user_id == self.user_uuid, ServicePrice.service_type == service_type)
            .first()
        )

    def _upsert_service_price(self, service_type: str, price: float):
        """Set the default price; return the prior price (None if newly created)."""
        row = self._get_service_price_row(service_type)
        if row is None:
            self.db.add(
                ServicePrice(
                    user_id=self.user_uuid,
                    service_type=service_type,
                    current_price=price,
                    source="auto",
                )
            )
            return None
        prior = row.current_price
        row.current_price = price
        row.source = "auto"
        return prior

    @staticmethod
    def _rec_to_dict(row: PricingRecommendation) -> dict:
        return {
            "id": row.id,
            "service_type": row.service_type,
            "sample_size": row.sample_size,
            "baseline_price": row.baseline_price,
            "recommended_price": row.recommended_price,
            "multiplier": row.multiplier,
            "direction": row.direction,
            "rationale": row.rationale,
            "signals": row.signals or {},
            "status": row.status,
            "prior_price": row.prior_price,
            "trigger": row.trigger,
            "applied_at": row.applied_at.isoformat() if row.applied_at else None,
            "reverted_at": row.reverted_at.isoformat() if row.reverted_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "outcome": row.outcome,
            "outcome_delta": row.outcome_delta,
            "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
        }
