"""
Expectation model service — the learned REFLECT calibrator (Phase 0, shadow).

Predicts the expected master-score for a decision from its decision-time KPI
sub-scores, using an interpretable ridge model fit per ``decision_type``. It runs
in SHADOW behind ``AINDY_INFINITY_LEARNED_SHADOW`` (default off): on each matured
decision it logs (features, learned_expected, heuristic_expected, actual_score) to
``InfinityExpectationPrediction`` and **drives nothing**. Each logged row is also a
complete training example, so the shadow ledger is self-sufficient — no runtime
``LoopAdjustment`` query needed for Phase 0.

`train()` fits ridge per decision_type once enough matured rows exist; `evaluate()`
reports learned-vs-heuristic MAE from the ledger — the soak evidence for the flip.
Everything here is app-owned and interpretable (coefficients stored in a table).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)

SHADOW_FLAG_ENV = "AINDY_INFINITY_LEARNED_SHADOW"

# Decision-time features: the 5 KPI sub-scores. decision_type is the grouping key
# (one model each), not a feature.
FEATURE_KEYS = [
    "execution_speed",
    "decision_efficiency",
    "ai_productivity_boost",
    "focus_quality",
    "masterplan_progress",
]
FEATURE_VERSION = 1

MIN_TRAIN_SAMPLES = 20
RIDGE_LAMBDA = 1.0
_TRUE = {"1", "true", "yes", "on"}


def shadow_enabled() -> bool:
    return os.getenv(SHADOW_FLAG_ENV, "").strip().lower() in _TRUE


def build_features(score_snapshot: dict | None) -> list[float]:
    """Decision-time feature vector from a KPI score snapshot (missing -> 0.0)."""
    snap = score_snapshot or {}
    features: list[float] = []
    for key in FEATURE_KEYS:
        val = snap.get(key)
        if val is None:
            val = snap.get(f"{key}_score")
        features.append(float(val) if val is not None else 0.0)
    return features


# ── numpy ridge (interpretable, in-process) ──────────────────────────────────

def _fit_ridge(X: list[list[float]], y: list[float], lam: float = RIDGE_LAMBDA) -> list[float]:
    """Ridge via the normal equations with an un-regularized bias. Returns [w.., b]."""
    Xa = np.asarray(X, dtype=float)
    ya = np.asarray(y, dtype=float)
    n, d = Xa.shape
    Xb = np.hstack([Xa, np.ones((n, 1))])
    reg = lam * np.eye(d + 1)
    reg[-1, -1] = 0.0  # do not regularize the bias term
    coefs = np.linalg.solve(Xb.T @ Xb + reg, Xb.T @ ya)
    return [float(c) for c in coefs]


def _predict_coefs(coefs: list[float], features: list[float]) -> float:
    w = np.asarray(coefs, dtype=float)
    x = np.asarray(list(features) + [1.0], dtype=float)
    return float(np.clip(float(x @ w), 0.0, 100.0))


def _mae(preds: list[float], actuals: list[float]) -> float | None:
    if not actuals:
        return None
    return round(sum(abs(p - a) for p, a in zip(preds, actuals)) / len(actuals), 3)


# ── model access ─────────────────────────────────────────────────────────────

def _get_model(db, decision_type: str):
    from apps.analytics.expectation_model import InfinityExpectationModel

    return (
        db.query(InfinityExpectationModel)
        .filter(InfinityExpectationModel.decision_type == decision_type)
        .first()
    )


def predict_expected(db, decision_type: str, features: list[float]) -> float | None:
    """Learned expected score, or None if no usable model exists (abstain)."""
    model = _get_model(db, decision_type)
    if model is None or not model.coefficients:
        return None
    coefs = list(model.coefficients)
    if len(coefs) != len(features) + 1:
        return None  # feature-schema drift -> abstain to the heuristic
    return _predict_coefs(coefs, features)


# ── shadow logging (the hook) ────────────────────────────────────────────────

def shadow_log_expectation(
    db,
    *,
    loop_adjustment_id,
    decision_type: str | None,
    score_snapshot: dict | None,
    heuristic_expected,
    actual_score,
) -> dict | None:
    """Log a shadow prediction next to the heuristic. No-op when the flag is off.

    Isolated: manages its own commit/rollback so it can never perturb the caller's
    transaction, and never raises into the loop.
    """
    if not shadow_enabled():
        return None
    from apps.analytics.expectation_model import InfinityExpectationPrediction

    try:
        features = build_features(score_snapshot)
        learned = predict_expected(db, decision_type, features) if decision_type else None
        row = InfinityExpectationPrediction(
            loop_adjustment_id=str(loop_adjustment_id) if loop_adjustment_id is not None else None,
            decision_type=decision_type or "unknown",
            features=features,
            learned_expected=learned,
            heuristic_expected=float(heuristic_expected) if heuristic_expected is not None else None,
            actual_score=float(actual_score) if actual_score is not None else None,
        )
        db.add(row)
        db.commit()
        return {"prediction_id": row.id, "learned_expected": learned}
    except Exception as exc:  # never break REFLECT
        logger.warning("[ExpectationModel] shadow log failed (non-fatal): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None


# ── training + evaluation ────────────────────────────────────────────────────

def _upsert_model(db, decision_type: str, coefs: list[float], holdout_mae, sample_size: int) -> None:
    from apps.analytics.expectation_model import InfinityExpectationModel

    model = _get_model(db, decision_type)
    if model is None:
        model = InfinityExpectationModel(decision_type=decision_type)
        db.add(model)
    model.coefficients = coefs
    model.feature_keys = list(FEATURE_KEYS)
    model.feature_version = FEATURE_VERSION
    model.sample_size = sample_size
    model.holdout_mae = holdout_mae
    model.trained_at = datetime.now(timezone.utc)


def train(db) -> dict:
    """Fit ridge per decision_type from matured shadow rows. Abstains below the floor."""
    from apps.analytics.expectation_model import InfinityExpectationPrediction

    rows = (
        db.query(InfinityExpectationPrediction)
        .filter(InfinityExpectationPrediction.actual_score.isnot(None))
        .order_by(InfinityExpectationPrediction.created_at.asc())
        .all()
    )
    grouped: dict[str, list[tuple[list[float], float]]] = {}
    for row in rows:
        if not row.features:
            continue
        grouped.setdefault(row.decision_type, []).append((list(row.features), float(row.actual_score)))

    summary = {"trained": [], "skipped": []}
    for decision_type, examples in grouped.items():
        if len(examples) < MIN_TRAIN_SAMPLES:
            summary["skipped"].append(
                {"decision_type": decision_type, "reason": f"insufficient samples ({len(examples)} < {MIN_TRAIN_SAMPLES})"}
            )
            continue
        X = [ex[0] for ex in examples]
        y = [ex[1] for ex in examples]
        # Deterministic holdout: last 20% (rows are time-ordered).
        split = max(1, int(len(examples) * 0.8))
        if split < len(examples):
            coefs_train = _fit_ridge(X[:split], y[:split])
            holdout_mae = _mae([_predict_coefs(coefs_train, X[i]) for i in range(split, len(X))], y[split:])
        else:
            holdout_mae = None
        coefs_full = _fit_ridge(X, y)  # deploy coefficients fit on all data
        _upsert_model(db, decision_type, coefs_full, holdout_mae, len(examples))
        summary["trained"].append(
            {"decision_type": decision_type, "sample_size": len(examples), "holdout_mae": holdout_mae}
        )

    db.commit()
    return summary


def evaluate(db) -> dict:
    """Learned-vs-heuristic MAE from the shadow ledger — the soak report."""
    from apps.analytics.expectation_model import InfinityExpectationModel, InfinityExpectationPrediction

    rows = (
        db.query(InfinityExpectationPrediction)
        .filter(
            InfinityExpectationPrediction.actual_score.isnot(None),
            InfinityExpectationPrediction.learned_expected.isnot(None),
        )
        .all()
    )
    by_dt: dict[str, list] = {}
    for row in rows:
        by_dt.setdefault(row.decision_type, []).append(row)

    report: dict = {"shadow_enabled": shadow_enabled(), "overall": None, "by_decision_type": {}}
    all_learned: list[float] = []
    all_heur: list[float] = []
    for decision_type, rs in by_dt.items():
        learned_err = [abs(r.learned_expected - r.actual_score) for r in rs]
        heur_err = [
            abs((r.heuristic_expected if r.heuristic_expected is not None else r.actual_score) - r.actual_score)
            for r in rs
        ]
        report["by_decision_type"][decision_type] = {
            "n": len(rs),
            "learned_mae": round(sum(learned_err) / len(learned_err), 3),
            "heuristic_mae": round(sum(heur_err) / len(heur_err), 3),
            "learned_wins": sum(learned_err) < sum(heur_err),
        }
        all_learned += learned_err
        all_heur += heur_err

    if all_learned:
        report["overall"] = {
            "n": len(all_learned),
            "learned_mae": round(sum(all_learned) / len(all_learned), 3),
            "heuristic_mae": round(sum(all_heur) / len(all_heur), 3),
            "learned_wins": sum(all_learned) < sum(all_heur),
        }

    report["models"] = [
        {
            "decision_type": m.decision_type,
            "coefficients": m.coefficients,
            "feature_keys": m.feature_keys,
            "sample_size": m.sample_size,
            "holdout_mae": m.holdout_mae,
            "trained_at": m.trained_at.isoformat() if m.trained_at else None,
        }
        for m in db.query(InfinityExpectationModel).all()
    ]
    return report
