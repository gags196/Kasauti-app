import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from kasauti_api.db.base import Base


class LlmFeature(enum.Enum):
    pyq_ingestion = "pyq_ingestion"
    pyq_tagging = "pyq_tagging"
    math_extraction = "math_extraction"
    rubric_eval = "rubric_eval"
    embedding = "embedding"
    benchmark = "benchmark"
    topic_analysis = "topic_analysis"
    one_pager = "one_pager"
    question_profile = "question_profile"
    prediction_scoring = "prediction_scoring"


class LlmUsageEvent(Base):
    """Per-call token/cost ledger — every LLM and embedding call writes one row.

    Aggregated by the llm_cost_daily_by_feature materialized view (created in the
    initial migration) for the founder cost dashboard in /admin.
    """

    __tablename__ = "llm_usage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    feature: Mapped[LlmFeature] = mapped_column(Enum(LlmFeature, name="llm_feature"))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6))
    related_entity_type: Mapped[str | None] = mapped_column(String(64))
    related_entity_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_llm_usage_feature_date", "feature", "created_at"),)
