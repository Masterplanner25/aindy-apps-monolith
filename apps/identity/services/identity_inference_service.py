"""
Identity inference — evidence model (rules -> probabilistic).

The rules-only path flipped a UserIdentity dimension on a single observation and never
revised it. This module makes inference a weighted, recency-aware vote over accumulated
evidence (`IdentitySignal`): every observation is a vote for a categorical value with a
strength; a dimension is *committed* only when the leading value clears a confidence
floor and has enough total support, and an already-committed value is only replaced when
the new leader beats it by a margin (hysteresis) — so one off-pattern event can't churn
the profile, and sustained counter-evidence still moves it.

Interpretable and in-process: the "model" is a transparent multinomial over evidence
weights with exponential recency decay — no opaque parameters, and every verdict exposes
its full distribution, confidence, and support for inspection.
"""
from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id
from apps.identity.models.identity_signal import IdentitySignal

logger = logging.getLogger(__name__)

# A value is only committed to UserIdentity when the leading share of evidence weight
# clears this floor and total support reaches MIN_SUPPORT; replacing an already-set value
# additionally requires beating its share by SWITCH_MARGIN so the profile doesn't churn.
CONFIDENCE_THRESHOLD = 0.6
MIN_SUPPORT = 2.0
SWITCH_MARGIN = 0.15

# Recency: older evidence decays exponentially so the profile tracks the user as they
# change, without discarding history outright. Half-life in days (env-overridable).
_DEFAULT_HALF_LIFE_DAYS = 30.0


def _half_life_days() -> float:
    raw = os.environ.get("AINDY_IDENTITY_EVIDENCE_HALF_LIFE_DAYS", "").strip()
    try:
        val = float(raw) if raw else _DEFAULT_HALF_LIFE_DAYS
        return val if val > 0 else _DEFAULT_HALF_LIFE_DAYS
    except ValueError:
        return _DEFAULT_HALF_LIFE_DAYS


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _decay(created_at, reference: datetime, half_life_days: float) -> float:
    """Exponential recency weight in (0, 1]; 1.0 for a signal as new as ``reference``."""
    if created_at is None:
        return 1.0
    try:
        age_days = max(0.0, (_as_utc(reference) - _as_utc(created_at)).total_seconds() / 86400.0)
    except Exception:
        return 1.0
    return math.pow(0.5, age_days / half_life_days)


def record_signal(
    db: Session,
    user_id,
    dimension: str,
    value: str,
    *,
    weight: float = 1.0,
    event_type: str | None = None,
) -> IdentitySignal | None:
    """Append one weighted evidence vote. Returns the row, or None on a bad value."""
    uid = parse_user_id(user_id)
    if uid is None or not dimension or not value:
        return None
    row = IdentitySignal(
        user_id=uid,
        dimension=str(dimension),
        value=str(value)[:64],
        weight=float(weight),
        event_type=(str(event_type)[:64] if event_type else None),
        created_at=_now_utc(),  # explicit so recency is deterministic + tz-aware
    )
    db.add(row)
    db.flush()
    return row


def aggregate(db: Session, user_id, dimension: str) -> dict[str, float]:
    """Recency-decayed total evidence weight per candidate value for a dimension.

    Decay is measured relative to the *newest* signal in the set, so the freshest
    evidence keeps its full weight (decay 1.0) and older evidence is discounted
    against it. Anchoring to the newest signal (rather than wall-clock now) keeps the
    aggregate deterministic — sub-second timing never nudges a value below a support
    threshold — while still tracking the user as their evidence shifts over time.
    """
    uid = parse_user_id(user_id)
    if uid is None:
        return {}
    rows = (
        db.query(IdentitySignal)
        .filter(IdentitySignal.user_id == uid, IdentitySignal.dimension == dimension)
        .all()
    )
    if not rows:
        return {}
    timestamps = [r.created_at for r in rows if r.created_at is not None]
    reference = max(timestamps) if timestamps else _now_utc()
    half_life = _half_life_days()
    totals: dict[str, float] = {}
    for row in rows:
        w = float(row.weight or 0.0) * _decay(row.created_at, reference, half_life)
        totals[row.value] = totals.get(row.value, 0.0) + w
    # Round away negligible sub-second decay so evidence at an exact support threshold
    # isn't nudged below it by microsecond ordering; real decay (hours+) is preserved.
    return {value: round(total, 6) for value, total in totals.items()}


def infer_dimension(db: Session, user_id, dimension: str, *, current: str | None = None) -> dict:
    """Infer the leading value for a categorical dimension from accumulated evidence.

    Returns ``{value, confidence, support, distribution, committable}`` where
    ``committable`` is True only when the leader clears the confidence floor, has enough
    support, and (if a ``current`` value is set) beats it by the switch margin.
    """
    totals = aggregate(db, user_id, dimension)
    support = round(sum(totals.values()), 4)
    if not totals or support <= 0:
        return {"value": None, "confidence": 0.0, "support": 0.0, "distribution": {}, "committable": False}

    leader, leader_weight = max(totals.items(), key=lambda kv: kv[1])
    confidence = leader_weight / support
    distribution = {k: round(v / support, 4) for k, v in totals.items()}

    committable = confidence >= CONFIDENCE_THRESHOLD and support >= MIN_SUPPORT
    if committable and current is not None and current != leader:
        current_share = distribution.get(current, 0.0)
        committable = (confidence - current_share) >= SWITCH_MARGIN
    if current is not None and current == leader:
        # already reflects the leader — nothing to commit, but the read is still valid
        committable = False

    return {
        "value": leader,
        "confidence": round(confidence, 4),
        "support": support,
        "distribution": distribution,
        "committable": committable,
    }


def infer_ranked(db: Session, user_id, dimension: str, *, min_support: float = MIN_SUPPORT) -> list[str]:
    """Values whose accumulated evidence clears ``min_support``, strongest first.

    For list dimensions (languages, tools) — a candidate earns a place only after enough
    weighted evidence, so a one-off signal no longer becomes a permanent preference.
    """
    totals = aggregate(db, user_id, dimension)
    qualified = [(v, w) for v, w in totals.items() if w >= min_support]
    qualified.sort(key=lambda vw: vw[1], reverse=True)
    return [v for v, _ in qualified]


def dimension_summary(db: Session, user_id, dimension: str, *, current: str | None = None) -> dict:
    """Inspectable inference verdict for one dimension (for the /inference surface)."""
    result = infer_dimension(db, user_id, dimension, current=current)
    return {
        "dimension": dimension,
        "current": current,
        "inferred": result["value"],
        "confidence": result["confidence"],
        "support": result["support"],
        "distribution": result["distribution"],
        "committable": result["committable"],
    }
