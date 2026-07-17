"""
LEAD ACTION MODEL
------------------------------------
Part of: A.I.N.D.Y. – Search Execution Layer

The Execution Layer is the act-on-insight half Search was missing: the leadgen
pipeline discovered and scored leads (``LeadGenResult``) but nothing ever acted on
them. A ``LeadAction`` is that acted-upon artifact — one tracked, revertible row per
lead the guarded consumer decides to pursue, carrying the generated outreach draft
and the decision that qualified it.

Safe by construction: the default ``draft`` channel never contacts the lead — it
produces a draft for review and (via the search public surface) for freelance to
convert into a client/order. A real send channel is gated default-off.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from AINDY.db.database import Base


class LeadAction(Base):
    """One outreach action taken on a discovered lead (draft-first, revertible)."""

    __tablename__ = "lead_actions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    lead_id = Column(
        Integer,
        ForeignKey("leadgen_results.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Denormalized lead context (survives lead deletion; drives display).
    company = Column(String)
    url = Column(String)

    channel = Column(String(16), default="draft")     # draft | email | handoff
    status = Column(String(16), default="drafted", index=True)  # drafted | queued | sent | skipped | reverted

    # The generated outreach artifact (draft channel).
    draft_subject = Column(String)
    draft_body = Column(Text)

    # Why this lead qualified — the gate's decision, for audit.
    decision_score = Column(Float)
    decision_reason = Column(String)

    trigger = Column(String(16), default="manual")    # manual | agent | scheduler
    note = Column(String)                             # e.g. "send channel disabled"

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    reverted_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<LeadAction(company='{self.company}', status='{self.status}')>"
