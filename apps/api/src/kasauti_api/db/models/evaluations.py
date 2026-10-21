import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kasauti_api.db.base import Base


class SubmissionLanguage(enum.Enum):
    en = "en"
    hi = "hi"


class EvaluationStatus(enum.Enum):
    processing = "processing"
    auto_scored = "auto_scored"
    pending_human_review = "pending_human_review"
    human_reviewed = "human_reviewed"
    published = "published"


class VerificationMethod(enum.Enum):
    symbolic = "symbolic"
    llm_judged = "llm_judged"
    human = "human"


class AnswerSubmission(Base):
    __tablename__ = "answer_submissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"))
    image_refs: Mapped[list[str]] = mapped_column(ARRAY(String(512)))  # R2 keys
    language: Mapped[SubmissionLanguage] = mapped_column(
        Enum(SubmissionLanguage, name="submission_language")
    )
    extracted_text: Mapped[str | None] = mapped_column(Text)
    # Segmented steps: [{"step": 1, "text": ..., "latex": ...}, ...]
    extracted_steps: Mapped[list | None] = mapped_column(JSON)
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    evaluations: Mapped[list["Evaluation"]] = relationship(back_populates="submission")


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("answer_submissions.id"))
    rubric_id: Mapped[str] = mapped_column(String(200))
    rubric_version: Mapped[str] = mapped_column(String(32))
    model_provider: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(128))
    total_marks_possible: Mapped[float] = mapped_column(Numeric(6, 2))
    # Always sum(evaluation_steps.marks_awarded) computed in Python — never an LLM output.
    total_marks_awarded: Mapped[float | None] = mapped_column(Numeric(6, 2))
    confidence_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[EvaluationStatus] = mapped_column(
        Enum(EvaluationStatus, name="evaluation_status"), default=EvaluationStatus.processing
    )
    human_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    submission: Mapped[AnswerSubmission] = relationship(back_populates="evaluations")
    steps: Mapped[list["EvaluationStep"]] = relationship(back_populates="evaluation")

    __table_args__ = (Index("ix_evaluations_status", "status"),)


class EvaluationStep(Base):
    __tablename__ = "evaluation_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"))
    step_number: Mapped[int] = mapped_column()
    rubric_criterion_id: Mapped[str] = mapped_column(String(128))
    criterion_description_en: Mapped[str | None] = mapped_column(Text)
    criterion_description_hi: Mapped[str | None] = mapped_column(Text)
    marks_possible: Mapped[float] = mapped_column(Numeric(6, 2))
    marks_awarded: Mapped[float] = mapped_column(Numeric(6, 2))
    verification_method: Mapped[VerificationMethod] = mapped_column(
        Enum(VerificationMethod, name="verification_method")
    )
    # symbolic: checker name/inputs/result; llm_judged: verdict/reasoning; human: reviewer note
    verification_detail: Mapped[dict | None] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float)

    evaluation: Mapped[Evaluation] = relationship(back_populates="steps")
    citations: Mapped[list["EvaluationStepCitation"]] = relationship(back_populates="step")

    __table_args__ = (Index("ix_evaluation_steps_eval", "evaluation_id"),)


class EvaluationStepCitation(Base):
    __tablename__ = "evaluation_step_citations"

    evaluation_step_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_steps.id"), primary_key=True
    )
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), primary_key=True)

    step: Mapped[EvaluationStep] = relationship(back_populates="citations")
