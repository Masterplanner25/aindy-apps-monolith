"""
Identity Service — v5 Phase 2

Manages user identity profiles. Observes patterns from
workflow behavior and updates identity incrementally.

Key principle: Identity is inferred, not declared.
A.I.N.D.Y. watches what users do and builds a picture
of who they are over time. Users can also explicitly
set preferences.

Evolution tracking: every change is logged with what
changed, why, and when. The identity layer evolves
alongside the user.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class IdentityService:
    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id

    def get_or_create(self) -> "UserIdentity":
        """
        Get the user's identity profile.
        Creates a blank profile if none exists.
        """
        from AINDY.db.models.user_identity import UserIdentity

        identity = (
            self.db.query(UserIdentity)
            .filter(UserIdentity.user_id == UUID(str(self.user_id)))
            .first()
        )

        if not identity:
            identity = UserIdentity(
                user_id=UUID(str(self.user_id)),
                preferred_languages=[],
                preferred_tools=[],
                avoided_tools=[],
                evolution_log=[],
            )
            self.db.add(identity)
            self.db.commit()
            self.db.refresh(identity)

        return identity

    def get_profile(self) -> dict:
        """
        Get the user's full identity profile as a dict.
        Returns a clean summary for use in prompts and UI.
        """
        identity = self.get_or_create()

        return {
            "user_id": self.user_id,
            "communication": {
                "tone": identity.tone,
                "notes": identity.communication_notes,
            },
            "tools": {
                "preferred_languages": identity.preferred_languages or [],
                "preferred_tools": identity.preferred_tools or [],
                "avoided_tools": identity.avoided_tools or [],
            },
            "decision_making": {
                "risk_tolerance": identity.risk_tolerance,
                "speed_vs_quality": identity.speed_vs_quality,
                "notes": identity.decision_notes,
            },
            "learning": {
                "style": identity.learning_style,
                "detail_preference": identity.detail_preference,
                "notes": identity.learning_notes,
            },
            "evolution": {
                "observation_count": identity.observation_count or 0,
                "last_updated": (
                    identity.last_updated.isoformat()
                    if identity.last_updated
                    else None
                ),
                "change_count": len(identity.evolution_log or []),
            },
        }

    def update_explicit(
        self,
        tone: str = None,
        preferred_languages: list = None,
        preferred_tools: list = None,
        avoided_tools: list = None,
        risk_tolerance: str = None,
        speed_vs_quality: str = None,
        learning_style: str = None,
        detail_preference: str = None,
        communication_notes: str = None,
        decision_notes: str = None,
        learning_notes: str = None,
    ) -> dict:
        """
        Explicitly set identity preferences.
        Called when user directly states their preferences.
        All changes are logged in evolution_log.
        """
        from AINDY.db.models.user_identity import (
            VALID_DETAIL_PREFERENCES,
            VALID_LEARNING_STYLES,
            VALID_RISK_TOLERANCE,
            VALID_SPEED_VS_QUALITY,
            VALID_TONES,
        )

        identity = self.get_or_create()
        changes = []
        now = _now_utc()

        def record_change(dimension, old, new, trigger="explicit"):
            if old != new and new is not None:
                changes.append(
                    {
                        "timestamp": now.isoformat(),
                        "dimension": dimension,
                        "old_value": old,
                        "new_value": new,
                        "trigger": trigger,
                    }
                )

        if tone and tone in VALID_TONES:
            record_change("tone", identity.tone, tone)
            identity.tone = tone

        if preferred_languages is not None:
            record_change(
                "preferred_languages",
                identity.preferred_languages,
                preferred_languages,
            )
            identity.preferred_languages = preferred_languages

        if preferred_tools is not None:
            record_change(
                "preferred_tools", identity.preferred_tools, preferred_tools
            )
            identity.preferred_tools = preferred_tools

        if avoided_tools is not None:
            record_change(
                "avoided_tools", identity.avoided_tools, avoided_tools
            )
            identity.avoided_tools = avoided_tools

        if risk_tolerance and risk_tolerance in VALID_RISK_TOLERANCE:
            record_change(
                "risk_tolerance", identity.risk_tolerance, risk_tolerance
            )
            identity.risk_tolerance = risk_tolerance

        if speed_vs_quality and speed_vs_quality in VALID_SPEED_VS_QUALITY:
            record_change(
                "speed_vs_quality",
                identity.speed_vs_quality,
                speed_vs_quality,
            )
            identity.speed_vs_quality = speed_vs_quality

        if learning_style and learning_style in VALID_LEARNING_STYLES:
            record_change(
                "learning_style", identity.learning_style, learning_style
            )
            identity.learning_style = learning_style

        if detail_preference and detail_preference in VALID_DETAIL_PREFERENCES:
            record_change(
                "detail_preference",
                identity.detail_preference,
                detail_preference,
            )
            identity.detail_preference = detail_preference

        if communication_notes:
            identity.communication_notes = communication_notes
        if decision_notes:
            identity.decision_notes = decision_notes
        if learning_notes:
            identity.learning_notes = learning_notes

        if changes:
            log = list(identity.evolution_log or [])
            log.extend(changes)
            identity.evolution_log = log
            identity.last_updated = now
            identity.observation_count = (
                identity.observation_count or 0
            ) + len(changes)

        self.db.add(identity)
        self.db.commit()
        self.db.refresh(identity)

        return {
            "changes_recorded": len(changes),
            "changes": changes,
            "profile": self.get_profile(),
        }

    def observe(self, event_type: str, context: dict) -> None:
        """
        Observe a workflow event and infer identity signals.
        Called automatically by the capture engine.

        This is how identity is built without explicit input — A.I.N.D.Y. watches
        what the user does and infers their preferences over time. Rather than
        flipping a dimension on a single observation, each event is recorded as
        weighted evidence (`IdentitySignal`) and the affected dimensions are
        re-derived from the accumulated evidence: a value is committed only when the
        inference is confident and well-supported, and an already-set value is only
        replaced when the new evidence beats it by a margin (see
        `identity_inference_service`). One off-pattern event no longer churns the
        profile; sustained counter-evidence still moves it.
        """
        try:
            from apps.identity.services import identity_inference_service as inference

            signals = self._event_to_signals(event_type, context)
            if not signals:
                return

            identity = self.get_or_create()
            now = _now_utc()

            for dimension, value, weight in signals:
                inference.record_signal(
                    self.db, self.user_id, dimension, value,
                    weight=weight, event_type=event_type,
                )

            dims = {dimension for dimension, _, _ in signals}
            changes = self._commit_inferred_dimensions(identity, dims, event_type, now, inference)

            # Every observation counts, whether or not it moved a dimension — the
            # evidence itself is the record. Always commit so the signal rows persist.
            identity.observation_count = (identity.observation_count or 0) + 1
            if changes:
                log = list(identity.evolution_log or [])
                log.extend(changes)
                identity.evolution_log = log
                identity.last_updated = now
            self.db.add(identity)
            self.db.commit()
        except Exception as e:
            logger.warning(f"Identity observation failed: {e}")
            try:
                self.db.rollback()
            except Exception:  # pragma: no cover - defensive
                pass

    # Posture -> risk tolerance evidence (an explicit posture is stronger evidence).
    _POSTURE_TO_RISK = {
        "aggressive": "aggressive",
        "accelerated": "moderate",
        "stable": "conservative",
        "reduced": "conservative",
    }

    @staticmethod
    def _event_to_signals(event_type: str, context: dict) -> list[tuple[str, str, float]]:
        """Translate a workflow event into weighted (dimension, value, weight) votes."""
        signals: list[tuple[str, str, float]] = []
        context = context or {}

        if event_type in ("arm_analysis_complete", "arm_generation_complete"):
            lang = context.get("language") or context.get("file_type")
            if lang:
                clean = str(lang).strip().strip(".")
                if clean:
                    signals.append(("language", clean, 1.0))

        if event_type == "arm_analysis_complete":
            score = context.get("score")
            if isinstance(score, (int, float)):
                # High-quality output is evidence of a quality bias; fast, low-scoring
                # output is evidence of a speed bias — counter-evidence, both directions.
                if score >= 8:
                    signals.append(("speed_vs_quality", "quality", 1.0))
                elif score <= 4:
                    signals.append(("speed_vs_quality", "speed", 1.0))
                else:
                    signals.append(("speed_vs_quality", "balanced", 0.5))

        if event_type == "masterplan_locked":
            inferred_risk = IdentityService._POSTURE_TO_RISK.get(context.get("posture"))
            if inferred_risk:
                signals.append(("risk_tolerance", inferred_risk, 1.5))

        return signals

    def _commit_inferred_dimensions(self, identity, dims: set, event_type: str, now, inference) -> list:
        """Re-derive each affected dimension from evidence; commit confident verdicts."""
        from AINDY.db.models.user_identity import (
            VALID_RISK_TOLERANCE,
            VALID_SPEED_VS_QUALITY,
        )

        changes = []

        # Single-value categorical dimensions.
        for dim, field, valid in (
            ("speed_vs_quality", "speed_vs_quality", VALID_SPEED_VS_QUALITY),
            ("risk_tolerance", "risk_tolerance", VALID_RISK_TOLERANCE),
        ):
            if dim not in dims:
                continue
            current = getattr(identity, field)
            verdict = inference.infer_dimension(self.db, self.user_id, dim, current=current)
            new_value = verdict["value"]
            if verdict["committable"] and new_value in valid and new_value != current:
                setattr(identity, field, new_value)
                changes.append({
                    "timestamp": now.isoformat(),
                    "dimension": field,
                    "old_value": current,
                    "new_value": new_value,
                    "confidence": verdict["confidence"],
                    "support": verdict["support"],
                    "trigger": f"inferred:{event_type}",
                })

        # List dimension: languages ranked by evidence, only those clearing support.
        if "language" in dims:
            ranked = inference.infer_ranked(self.db, self.user_id, "language")
            current_langs = list(identity.preferred_languages or [])
            if ranked and ranked != current_langs:
                identity.preferred_languages = ranked
                changes.append({
                    "timestamp": now.isoformat(),
                    "dimension": "preferred_languages",
                    "old_value": current_langs,
                    "new_value": ranked,
                    "trigger": f"inferred:{event_type}",
                })

        return changes

    def get_inference_summary(self) -> dict:
        """Inspectable view of the evidence behind each inferred dimension.

        Surfaces, per dimension, the currently committed value, the value the
        accumulated evidence points to, its confidence and support, and the full
        distribution — so the probabilistic inference is transparent, not a black box.
        """
        from apps.identity.services import identity_inference_service as inference

        identity = self.get_or_create()
        dimensions = [
            inference.dimension_summary(
                self.db, self.user_id, "speed_vs_quality", current=identity.speed_vs_quality
            ),
            inference.dimension_summary(
                self.db, self.user_id, "risk_tolerance", current=identity.risk_tolerance
            ),
        ]
        language_evidence = inference.aggregate(self.db, self.user_id, "language")
        return {
            "user_id": self.user_id,
            "dimensions": dimensions,
            "languages": {
                "current": identity.preferred_languages or [],
                "inferred": inference.infer_ranked(self.db, self.user_id, "language"),
                "evidence": {k: round(v, 4) for k, v in language_evidence.items()},
            },
        }

    def get_context_for_prompt(self) -> str:
        """
        Generate a context string for injecting user
        identity into LLM prompts.
        """
        profile = self.get_profile()
        parts = []

        tone = profile["communication"]["tone"]
        if tone:
            parts.append(f"Communication style: {tone}")

        langs = profile["tools"]["preferred_languages"]
        if langs:
            parts.append(f"Preferred languages: {', '.join(langs)}")

        risk = profile["decision_making"]["risk_tolerance"]
        if risk:
            parts.append(f"Risk tolerance: {risk}")

        style = profile["learning"]["style"]
        detail = profile["learning"]["detail_preference"]
        if style or detail:
            learning = []
            if style:
                learning.append(style)
            if detail:
                learning.append(detail.replace("_", " "))
            parts.append(f"Learning preference: {', '.join(learning)}")

        if not parts:
            return ""

        return "\n\nUser identity context:\n" + "\n".join(
            f"- {p}" for p in parts
        )

    def get_evolution_summary(self) -> dict:
        """
        Summarize how the user's identity has evolved.
        Shows the arc of change over time.
        """
        identity = self.get_or_create()
        log = identity.evolution_log or []

        if not log:
            return {
                "message": (
                    "Identity profile is new. Patterns will emerge as you use "
                    "A.I.N.D.Y."
                ),
                "observation_count": 0,
                "total_changes": 0,
                "dimensions_evolved": [],
                "most_changed_dimension": None,
                "recent_changes": [],
                "evolution_arc": (
                    "No observations yet. Use A.I.N.D.Y. features to build "
                    "your identity profile."
                ),
                "changes": [],
            }

        by_dimension = {}
        for entry in log:
            dim = entry.get("dimension", "unknown")
            if dim not in by_dimension:
                by_dimension[dim] = []
            by_dimension[dim].append(entry)

        most_changed = sorted(
            by_dimension.items(), key=lambda x: len(x[1]), reverse=True
        )

        return {
            "observation_count": identity.observation_count or 0,
            "total_changes": len(log),
            "dimensions_evolved": list(by_dimension.keys()),
            "most_changed_dimension": most_changed[0][0]
            if most_changed
            else None,
            "recent_changes": log[-5:],
            "evolution_arc": (
                f"Your identity has been observed "
                f"{identity.observation_count} times with "
                f"{len(log)} preference updates across "
                f"{len(by_dimension)} dimensions."
            ),
        }

