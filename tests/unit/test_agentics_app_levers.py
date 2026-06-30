"""App-owned Agentics decision levers (AGENTICS.md hardening).

AGENTICS is overwhelmingly runtime-owned (it is the doc that defined the
`aindy-runtime` split). The app's genuine contribution is the *decision* logic it
registers into the runtime via `register_*` hooks — and it was untested. This
covers the three app-owned levers:

- Phase C: the autonomy trigger evaluator (`apps/agent/agents/triggers.py`) — the
  execute/defer/ignore policy used for every trigger type via the "default" hook.
- Phase D: the agent ranking strategy (`apps/masterplan/agents/ranking.py`).
- Phase A/C: the agent completion hook (`apps/agent/agents/runtime_extensions.py`)
  that enforces the Infinity loop after a run.

All pure/injectable — no runtime edits, no live execution stack.
"""

from __future__ import annotations

import pytest

from apps.agent.agents.runtime_extensions import handle_agent_run_completed
from apps.agent.agents.triggers import evaluate_autonomy_trigger
from apps.masterplan.agents.ranking import rank_agents

pytestmark = pytest.mark.app_profile


# --------------------------------------------------------------------------- #
# Phase C — autonomy trigger evaluator (execute / defer / ignore policy)
# --------------------------------------------------------------------------- #
# No "db" in context -> _enrich_context is a no-op, so the decision is computed
# purely from the provided trigger + context.
def test_trigger_executes_high_value_user_trigger():
    out = evaluate_autonomy_trigger({"trigger_type": "user", "trigger": {"importance": 0.95}, "context": {}})
    assert out["decision"] == "execute"
    assert out["priority"] == pytest.approx(0.7625)
    assert out["defer_seconds"] == 0


def test_trigger_defers_when_system_health_critical():
    out = evaluate_autonomy_trigger(
        {"trigger_type": "watcher", "trigger": {}, "context": {"system_state": {"health_status": "critical"}}}
    )
    assert out["decision"] == "defer"
    assert out["defer_seconds"] == 300
    assert "critical" in out["reason"]


def test_trigger_defers_under_high_load():
    out = evaluate_autonomy_trigger(
        {"trigger_type": "watcher", "trigger": {}, "context": {"system_state": {"system_load": 0.9}}}
    )
    assert out["decision"] == "defer"
    assert "load" in out["reason"]


def test_trigger_defers_on_repeated_failure_pattern():
    out = evaluate_autonomy_trigger(
        {"trigger_type": "schedule", "trigger": {}, "context": {"ripple_patterns": [{"failure_events": 3}]}}
    )
    assert out["decision"] == "defer"
    assert "repeated failures" in out["reason"]


def test_trigger_ignores_low_value_watcher():
    out = evaluate_autonomy_trigger(
        {
            "trigger_type": "watcher",
            "trigger": {},
            "context": {
                "memory_signals": [
                    {"type": "failure", "impact_score": 1.0},
                    {"type": "failure", "impact_score": 1.0},
                    {"type": "failure"},
                ]
            },
        }
    )
    assert out["decision"] == "ignore"
    assert out["priority"] < 0.35


def test_autonomy_trigger_evaluator_registered():
    from AINDY.platform_layer.registry import get_trigger_evaluator

    # All trigger types fall back to "default" -> the app-owned evaluator. The
    # runtime may wrap trigger evaluators (subprocess-capable surface), so assert
    # registration by presence rather than object identity.
    evaluator = get_trigger_evaluator("default")
    assert evaluator is not None and callable(evaluator)


# --------------------------------------------------------------------------- #
# Phase D — agent ranking strategy
# --------------------------------------------------------------------------- #
def test_rank_agents_sorts_by_coordination_score():
    candidates = [
        {"agent_id": "a", "coordination_score": 0.3},
        {"agent_id": "b", "coordination_score": 0.7},
    ]
    ranked = rank_agents(candidates, {})  # no db -> no goal bonus, just sort
    assert [c["agent_id"] for c in ranked] == ["b", "a"]
    # input is not mutated
    assert candidates[0]["agent_id"] == "a"


def test_rank_agents_applies_goal_alignment_bonus(monkeypatch):
    import AINDY.platform_layer.registry as registry
    import AINDY.platform_layer.system_state_service as system_state_service

    monkeypatch.setattr(
        registry,
        "get_job",
        lambda name: (lambda db, user_id, system_state=None: [{"name": "ship widget", "ranked_priority": 0.8}])
        if name == "goals.rank"
        else None,
    )
    monkeypatch.setattr(system_state_service, "compute_current_state", lambda db: {})

    ranked = rank_agents(
        [{"agent_id": "a", "coordination_score": 0.5}],
        {"db": object(), "user_id": "u1", "task": {"name": "ship widget"}},
    )
    # bonus = ranked_priority(0.8) * 0.15 = 0.12
    assert ranked[0]["coordination_score"] == pytest.approx(0.62)


def test_agent_ranking_strategy_registered():
    from AINDY.platform_layer.registry import get_agent_ranking_strategy

    assert get_agent_ranking_strategy() is rank_agents


# --------------------------------------------------------------------------- #
# Phase A/C — agent completion hook (enforces the Infinity loop post-run)
# --------------------------------------------------------------------------- #
class _FakeRun:
    def __init__(self, result=None, run_id="run-1"):
        self.result = {} if result is None else result
        self.id = run_id


class _FakeDB:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        pass


def test_completion_hook_enforces_infinity_loop(monkeypatch):
    import AINDY.platform_layer.registry as registry

    monkeypatch.setattr(
        registry,
        "get_job",
        lambda name: (lambda **kw: {"next_action": {"type": "continue_highest_priority_task"}})
        if name == "analytics.infinity_execute"
        else None,
    )
    run, db = _FakeRun(), _FakeDB()
    out = handle_agent_run_completed({"run": run, "db": db, "user_id": "u1"})
    assert out["loop_enforced"] is True
    assert out["next_action"]["type"] == "continue_highest_priority_task"
    assert run.result["loop_enforced"] is True
    assert db.committed is True


def test_completion_hook_noop_when_already_enforced(monkeypatch):
    import AINDY.platform_layer.registry as registry

    called = []
    monkeypatch.setattr(registry, "get_job", lambda name: called.append(name) or None)
    out = handle_agent_run_completed({"run": _FakeRun(result={"loop_enforced": True}), "db": _FakeDB(), "user_id": "u1"})
    assert out is None
    assert called == []  # short-circuits before touching the job registry


def test_completion_hook_graceful_without_orchestrator(monkeypatch):
    import AINDY.platform_layer.registry as registry

    monkeypatch.setattr(registry, "get_job", lambda name: None)
    out = handle_agent_run_completed({"run": _FakeRun(), "db": _FakeDB(), "user_id": "u1"})
    assert out is None  # missing job -> swallowed, run untouched


def test_completion_hook_requires_run_and_db():
    assert handle_agent_run_completed({"run": None, "db": None}) is None
