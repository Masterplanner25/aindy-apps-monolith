"""ARM auto-tune learning close — Reflect -> Adjust -> LEARN.

The auto-tune consumer applied changes but never checked whether they helped. This closes
the loop: after an observation window each applied change is judged against its
``metrics_snapshot`` (``_health`` = decision_efficiency − waste), a degraded change is
AUTO-REVERTED, and its key enters the gate's penalty box so the tuner stops re-applying it.
Covers the pure gate skip, ``_health``, and the DB-integration ``evaluate_outcomes`` path.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.arm.dao import arm_autotune_dao, arm_config_dao
from apps.arm.services.arm_autotune_service import (
    ARMAutoTuneService,
    OBSERVATION_HOURS,
    PENALTY_HOURS,
    _health,
    evaluate_autotune_gate,
)

pytestmark = pytest.mark.app_profile

_ENOUGH = {"total_sessions": 10}


def _bundle(param, new_val, *, risk="low"):
    return {"auto_apply_safe": [
        {"metric": "decision_efficiency", "risk": risk, "suggestion": "tune",
         "config_change": {param: new_val}}
    ]}


# ── gate penalty box (pure) ────────────────────────────────────────────────────
def test_gate_skips_degraded_keys_penalty_box():
    bundle = _bundle("temperature", 0.1)
    applied, skipped = evaluate_autotune_gate(
        bundle, {"temperature": 0.2}, _ENOUGH, degraded_keys={"temperature"}
    )
    assert applied == []
    assert len(skipped) == 1
    assert "penalty box" in skipped[0]["reason"]


def test_gate_applies_when_key_not_in_penalty_box():
    bundle = _bundle("temperature", 0.1)
    applied, _ = evaluate_autotune_gate(
        bundle, {"temperature": 0.2}, _ENOUGH, degraded_keys={"retry_limit"}
    )
    assert len(applied) == 1 and applied[0]["param"] == "temperature"


def test_health_scalar():
    assert _health({"decision_efficiency": 60, "waste_percentage": 10}) == pytest.approx(50.0)
    assert _health({}) == pytest.approx(0.0)
    # efficiency up + waste down = higher health
    assert _health({"decision_efficiency": 70, "waste_percentage": 5}) > _health(
        {"decision_efficiency": 50, "waste_percentage": 20}
    )


# ── evaluate_outcomes (DB integration) ─────────────────────────────────────────
def _matured_log(db, uid, *, snapshot, applied, prior_config):
    """Seed an applied, not-reverted, unevaluated log, backdated past the observation window."""
    log = arm_autotune_dao.create_log(
        db, user_id=uid, trigger="manual",
        applied=applied, skipped=[],
        prior_config=prior_config,
        resulting_config={**prior_config, **{c["param"]: c["new"] for c in applied}},
        metrics_snapshot=snapshot,
    )
    log.created_at = datetime.now(timezone.utc) - timedelta(hours=OBSERVATION_HOURS + 1)
    db.commit()
    return log


def _svc(db, uid, current_snapshot, monkeypatch):
    svc = ARMAutoTuneService(db=db, user_id=uid)
    monkeypatch.setattr(svc, "_metrics", lambda window=30: {})
    monkeypatch.setattr(svc, "_metrics_snapshot", lambda m: current_snapshot)
    return svc


def test_outcome_improved(db_session, monkeypatch):
    uid = str(uuid.uuid4())
    log = _matured_log(db_session, uid, snapshot={"decision_efficiency": 40, "waste_percentage": 10},
                       applied=[{"param": "temperature", "old": 0.2, "new": 0.1}],
                       prior_config={"temperature": 0.2})
    # health went 30 -> 55 (delta +25) => improved, no revert
    svc = _svc(db_session, uid, {"decision_efficiency": 60, "waste_percentage": 5}, monkeypatch)
    summary = svc.evaluate_outcomes()
    assert summary == {"evaluated": 1, "improved": 1, "degraded": 0, "neutral": 0,
                       "auto_reverted": 0, "results": summary["results"]}
    reloaded = arm_autotune_dao.get_log(db_session, log.id)
    assert reloaded.outcome == "improved" and reloaded.reverted is False


def test_outcome_degraded_auto_reverts(db_session, monkeypatch):
    uid = str(uuid.uuid4())
    # seed a config so there is something to revert against
    arm_config_dao.upsert_config(db_session, user_id=uid, temperature=0.1)
    log = _matured_log(db_session, uid, snapshot={"decision_efficiency": 50, "waste_percentage": 10},
                       applied=[{"param": "temperature", "old": 0.2, "new": 0.1}],
                       prior_config={"temperature": 0.2})
    # health 40 -> 20 (delta -20) => degraded => auto-revert restores temperature 0.2
    svc = _svc(db_session, uid, {"decision_efficiency": 30, "waste_percentage": 10}, monkeypatch)
    summary = svc.evaluate_outcomes()
    assert summary["degraded"] == 1 and summary["auto_reverted"] == 1
    reloaded = arm_autotune_dao.get_log(db_session, log.id)
    assert reloaded.outcome == "degraded" and reloaded.reverted is True
    # config restored to the pre-change value
    assert arm_config_dao.get_config(db_session, user_id=uid).temperature == pytest.approx(0.2)
    # and the degraded key is now in the penalty box
    since = datetime.now(timezone.utc) - timedelta(hours=PENALTY_HOURS)
    assert "temperature" in arm_autotune_dao.recently_degraded_keys(db_session, uid, since)


def test_outcome_neutral(db_session, monkeypatch):
    uid = str(uuid.uuid4())
    log = _matured_log(db_session, uid, snapshot={"decision_efficiency": 50, "waste_percentage": 10},
                       applied=[{"param": "retry_limit", "old": 3, "new": 4}],
                       prior_config={"retry_limit": 3})
    # health 40 -> 41 (delta +1, within ±3) => neutral
    svc = _svc(db_session, uid, {"decision_efficiency": 51, "waste_percentage": 10}, monkeypatch)
    summary = svc.evaluate_outcomes()
    assert summary["neutral"] == 1 and summary["auto_reverted"] == 0
    assert arm_autotune_dao.get_log(db_session, log.id).outcome == "neutral"


def test_unmatured_log_not_evaluated(db_session, monkeypatch):
    uid = str(uuid.uuid4())
    # a fresh (not backdated) log is too young to judge
    arm_autotune_dao.create_log(
        db_session, user_id=uid, trigger="manual",
        applied=[{"param": "temperature", "old": 0.2, "new": 0.1}], skipped=[],
        prior_config={"temperature": 0.2}, resulting_config={"temperature": 0.1},
        metrics_snapshot={"decision_efficiency": 50, "waste_percentage": 10},
    )
    svc = _svc(db_session, uid, {"decision_efficiency": 10, "waste_percentage": 90}, monkeypatch)
    assert svc.evaluate_outcomes()["evaluated"] == 0
