"""
Search Execution Layer — act on discovered leads.

Leadgen discovered and scored leads but nothing consumed them: the pipeline stopped
at retrieve -> score -> store -> list. This service is the missing act-on-insight
half. It takes the scored ``LeadGenResult`` rows, selects the ones worth pursuing
behind a safety gate, drafts outreach for each, and records a tracked, revertible
``LeadAction`` — the same guarded-consumer template ARM's auto-tune uses.

Safe by construction:
  * ``draft`` channel (default) never contacts the lead — it produces a draft for
    review and, via the search public surface, for freelance to convert.
  * ``email`` channel is gated default-off (``AINDY_SEARCH_OUTREACH_SEND``); with no
    provider wired in this cut it only ever queues a draft — nothing is sent.

The gate (``evaluate_lead_action_gate``) is a pure function, unit-tested without a DB.

Gate rules (all must pass for a lead to be actioned):
  * dedup        — a lead already actioned (non-reverted) is left alone
  * score        — overall_score must clear MIN_OVERALL_SCORE
  * data quality — data_quality_score must clear MIN_DATA_QUALITY
  * max per run  — at most MAX_ACTIONS_PER_RUN, highest-scoring first
"""
from __future__ import annotations

import logging
import os
import uuid

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import require_user_id
from apps.search.models.lead_action import LeadAction
from apps.search.models.leadgen_model import LeadGenResult

logger = logging.getLogger(__name__)


# ── Gate policy ───────────────────────────────────────────────────────────────

MIN_OVERALL_SCORE = 60.0
MIN_DATA_QUALITY = 50.0
MAX_ACTIONS_PER_RUN = 5

_SEND_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _outreach_send_enabled() -> bool:
    return os.getenv("AINDY_SEARCH_OUTREACH_SEND", "").strip().lower() in _SEND_ENABLED_VALUES


def evaluate_lead_action_gate(
    leads: list[dict],
    actioned_lead_ids: set,
    *,
    min_overall_score: float = MIN_OVERALL_SCORE,
    min_data_quality: float = MIN_DATA_QUALITY,
    max_actions: int = MAX_ACTIONS_PER_RUN,
) -> tuple[list[dict], list[dict]]:
    """
    Decide which scored leads warrant an outreach action. Pure: no I/O.
    Returns ``(selected, skipped)``.

    ``selected`` items: {lead_id, company, url, context, score, data_quality, reason}
    ``skipped`` items:  {lead_id, company, reason}
    """
    selected: list[dict] = []
    skipped: list[dict] = []

    # Highest-scoring first, so the per-run cap keeps the best leads.
    ranked = sorted(leads, key=lambda lead: (lead.get("overall_score") or 0), reverse=True)

    for lead in ranked:
        lead_id = lead.get("id")
        company = lead.get("company")
        overall = lead.get("overall_score") or 0
        data_quality = lead.get("data_quality_score")

        if lead_id in actioned_lead_ids:
            skipped.append({"lead_id": lead_id, "company": company, "reason": "already actioned"})
            continue
        if overall < min_overall_score:
            skipped.append(
                {"lead_id": lead_id, "company": company,
                 "reason": f"below score threshold ({overall} < {min_overall_score})"}
            )
            continue
        if data_quality is not None and data_quality < min_data_quality:
            skipped.append(
                {"lead_id": lead_id, "company": company,
                 "reason": f"insufficient data quality ({data_quality} < {min_data_quality})"}
            )
            continue
        if len(selected) >= max_actions:
            skipped.append(
                {"lead_id": lead_id, "company": company,
                 "reason": f"exceeds max {max_actions} actions/run"}
            )
            continue

        selected.append(
            {
                "lead_id": lead_id,
                "company": company,
                "url": lead.get("url"),
                "context": lead.get("context"),
                "score": overall,
                "data_quality": data_quality,
                "reason": f"qualified (score {overall})",
            }
        )

    return selected, skipped


# ── Service ───────────────────────────────────────────────────────────────────

class LeadExecutionService:
    """Per-user consumer that turns scored leads into tracked outreach actions."""

    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = require_user_id(user_id)
        self.user_uuid = uuid.UUID(str(self.user_id))

    # ── reads ─────────────────────────────────────────────────────────────────

    def _leads(self) -> list[dict]:
        rows = (
            self.db.query(LeadGenResult)
            .filter(LeadGenResult.user_id == self.user_uuid)
            .order_by(LeadGenResult.overall_score.desc(), LeadGenResult.id.desc())
            .all()
        )
        return [
            {
                "id": row.id,
                "company": row.company,
                "url": row.url,
                "context": row.context,
                "overall_score": row.overall_score,
                "data_quality_score": row.data_quality_score,
            }
            for row in rows
        ]

    def _actioned_lead_ids(self) -> set:
        rows = (
            self.db.query(LeadAction.lead_id)
            .filter(LeadAction.user_id == self.user_uuid, LeadAction.status != "reverted")
            .all()
        )
        return {row[0] for row in rows if row[0] is not None}

    def plan(self) -> dict:
        """Dry run: which leads *would* be actioned, and what's gated."""
        selected, skipped = evaluate_lead_action_gate(self._leads(), self._actioned_lead_ids())
        return {"selected": selected, "skipped": skipped, "would_act": bool(selected)}

    # ── writes ────────────────────────────────────────────────────────────────

    def execute(self, channel: str = "draft", trigger: str = "manual") -> dict:
        """Draft + record an action for each gated lead. Never sends in this cut."""
        proposal = self.plan()
        selected = proposal["selected"]

        if not selected:
            return {
                "status": "no_action",
                "dry_run": False,
                "actions": [],
                "skipped": proposal["skipped"],
                "count": 0,
            }

        status, note = self._resolve_channel(channel)
        actions = []
        for item in selected:
            draft = self._draft_outreach(item)
            row = LeadAction(
                user_id=self.user_uuid,
                lead_id=item["lead_id"],
                company=item["company"],
                url=item.get("url"),
                channel=channel,
                status=status,
                draft_subject=draft["subject"],
                draft_body=draft["body"],
                decision_score=item["score"],
                decision_reason=item["reason"],
                trigger=trigger,
                note=note,
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            actions.append(
                {
                    "action_id": row.id,
                    "lead_id": row.lead_id,
                    "company": row.company,
                    "status": row.status,
                    "channel": row.channel,
                }
            )

        return {
            "status": "executed",
            "dry_run": False,
            "actions": actions,
            "skipped": proposal["skipped"],
            "count": len(actions),
        }

    def revert(self, action_id) -> dict:
        """Mark an action reverted so its lead is eligible again."""
        try:
            action_pk = int(action_id)
        except (TypeError, ValueError):
            return {"status": "not_found", "action_id": str(action_id)}

        row = (
            self.db.query(LeadAction)
            .filter(LeadAction.id == action_pk, LeadAction.user_id == self.user_uuid)
            .first()
        )
        if row is None:
            return {"status": "not_found", "action_id": action_pk}
        if row.status == "reverted":
            return {"status": "already_reverted", "action_id": row.id}

        from datetime import datetime, timezone

        row.status = "reverted"
        row.reverted_at = datetime.now(timezone.utc)
        self.db.commit()
        return {"status": "reverted", "action_id": row.id, "lead_id": row.lead_id}

    def history(self, limit: int = 20) -> list[dict]:
        rows = (
            self.db.query(LeadAction)
            .filter(LeadAction.user_id == self.user_uuid)
            .order_by(LeadAction.created_at.desc(), LeadAction.id.desc())
            .limit(limit)
            .all()
        )
        return [self._to_dict(row) for row in rows]

    # ── channels + drafting ─────────────────────────────────────────────────────

    @staticmethod
    def _resolve_channel(channel: str) -> tuple[str, str | None]:
        """Map a channel to the resulting status. No channel sends in this cut."""
        if channel == "draft":
            return "drafted", None
        if channel == "email":
            if _outreach_send_enabled():
                # A real provider send would happen here — intentionally not wired.
                return "queued", "send enabled but no email provider wired; left queued"
            return "queued", "email send disabled (AINDY_SEARCH_OUTREACH_SEND off) — queued, not sent"
        if channel == "handoff":
            return "queued", "handed off for freelance conversion"
        return "drafted", f"unknown channel '{channel}', defaulted to draft"

    def _draft_outreach(self, item: dict) -> dict:
        """LLM-drafted outreach with a deterministic offline fallback."""
        try:
            return self._llm_draft(item)
        except Exception as exc:  # no key / circuit open / parse error -> template
            logger.info("[lead_exec] LLM draft unavailable, using template: %s", exc)
            return self._template_draft(item)

    @staticmethod
    def _llm_draft(item: dict) -> dict:
        from AINDY.config import settings
        from AINDY.platform_layer.external_call_service import perform_external_call
        from AINDY.platform_layer.openai_client import chat_completion, get_openai_client

        company = item.get("company") or "the team"
        context = (item.get("context") or "").strip()
        system_prompt = (
            "You are an outreach copywriter for an AI consulting studio. Write a short, "
            "specific, non-spammy first-touch email. Return ONLY JSON with keys "
            "'subject' and 'body'. No greeting placeholders like [Name]."
        )
        user_prompt = f"Company: {company}\nWhy they're a fit: {context}\nKeep the body under 120 words."

        completion = perform_external_call(
            service_name="openai",
            endpoint="chat.completions.create",
            model="gpt-4o-mini",
            method="openai.chat",
            extra={"purpose": "lead_outreach_draft", "company": company},
            operation=lambda: chat_completion(
                get_openai_client(),
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
            ),
        )
        import json
        import re

        text = (completion.choices[0].message.content or "").strip()
        if not text.startswith("{"):
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                text = match.group(0)
        parsed = json.loads(text)
        subject = str(parsed.get("subject") or "").strip()
        body = str(parsed.get("body") or "").strip()
        if not subject or not body:
            raise ValueError("draft missing subject/body")
        return {"subject": subject, "body": body}

    @staticmethod
    def _template_draft(item: dict) -> dict:
        company = item.get("company") or "there"
        context = (item.get("context") or "").strip()
        hook = f" We noticed {context[:140]}" if context else ""
        subject = f"Quick idea for {company}"
        body = (
            f"Hi {company} team,\n\n"
            f"We help teams put AI to work on concrete outcomes.{hook}\n\n"
            "If it's useful, I'd be glad to share a couple of specific ideas tailored to "
            "what you're building. Open to a short conversation?\n\n"
            "Best,\nA.I.N.D.Y."
        )
        return {"subject": subject, "body": body}

    @staticmethod
    def _to_dict(row: LeadAction) -> dict:
        return {
            "id": row.id,
            "lead_id": row.lead_id,
            "company": row.company,
            "url": row.url,
            "channel": row.channel,
            "status": row.status,
            "draft_subject": row.draft_subject,
            "draft_body": row.draft_body,
            "decision_score": row.decision_score,
            "decision_reason": row.decision_reason,
            "trigger": row.trigger,
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "reverted_at": row.reverted_at.isoformat() if row.reverted_at else None,
        }
