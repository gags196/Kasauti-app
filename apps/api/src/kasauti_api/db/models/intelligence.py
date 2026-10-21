"""MVP-scope intelligence tables (kasauti-mvp-scope-prelims-mains-intelligence.md):
topic pattern analyses with tracked prediction accuracy, and Mains one-pager notes."""

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from kasauti_api.db.base import Base


class AnalysisScope(enum.Enum):
    prelims = "prelims"
    mains = "mains"
    combined = "combined"


class TopicAnalysis(Base):
    """Feature A1: per-topic recurring-pattern summary + predicted angles.

    Predictions carry their own visible accuracy record (prediction_outcomes)
    rather than an unverified claim — same trust posture as Mains grading.
    """

    __tablename__ = "topic_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    scope: Mapped[AnalysisScope] = mapped_column(Enum(AnalysisScope, name="analysis_scope"))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    model_name: Mapped[str] = mapped_column(String(128))
    prompt_ref: Mapped[str] = mapped_column(String(256))  # versioned file in content/prompts
    question_count: Mapped[int] = mapped_column(Integer)  # corpus size it was built from
    pattern_summary_en: Mapped[str] = mapped_column(Text)
    pattern_summary_hi: Mapped[str] = mapped_column(Text)
    # [{angle_en, angle_hi, rationale_en}], most likely first
    predicted_angles: Mapped[list] = mapped_column(JSON)
    # Filled as later real papers confirm/refute angles: {hits, misses, checked_years: []}
    prediction_outcomes: Mapped[dict | None] = mapped_column(JSON)

    # A backtest analysis is generated deliberately blind to recent years so its angles
    # can be scored against papers it never saw. It is written *later* than the live one,
    # so without this flag the "newest analysis" query would serve the blinded version to
    # learners as the current view.
    is_backtest: Mapped[bool] = mapped_column(Boolean, server_default=false())
    corpus_year_min: Mapped[int | None] = mapped_column(Integer)
    corpus_year_max: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_topic_analyses_topic", "topic_id", "generated_at"),
        Index("ix_topic_analyses_live", "topic_id", "scope", "is_backtest", "generated_at"),
    )


class TopicNoteStatus(enum.Enum):
    draft = "draft"
    published = "published"


class TopicNote(Base):
    """Feature B: Mains one-pager revision note per topic, grouped by syllabus."""

    __tablename__ = "topic_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    model_name: Mapped[str] = mapped_column(String(128))
    prompt_ref: Mapped[str] = mapped_column(String(256))
    question_count: Mapped[int] = mapped_column(Integer)
    # Typed sections (anchor facts, PYQ angles, keywords…) — schema enforced at
    # generation time by the structured-output model, stored as JSON.
    content_en: Mapped[dict] = mapped_column(JSON)
    content_hi: Mapped[dict] = mapped_column(JSON)
    status: Mapped[TopicNoteStatus] = mapped_column(
        Enum(TopicNoteStatus, name="topic_note_status"), default=TopicNoteStatus.draft
    )

    __table_args__ = (Index("ix_topic_notes_topic", "topic_id", "version"),)
