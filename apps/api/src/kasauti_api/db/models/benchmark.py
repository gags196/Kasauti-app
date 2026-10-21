import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kasauti_api.db.base import Base


class BenchmarkTrigger(enum.Enum):
    rubric_change = "rubric_change"
    model_swap = "model_swap"
    manual = "manual"
    ci = "ci"


class BenchmarkRunStatus(enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class LabeledAnswerSet(Base):
    __tablename__ = "labeled_answer_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    description: Mapped[str | None] = mapped_column(Text)
    # Provenance: who scored these answers (evaluator seniority etc.) — feeds the public report.
    source_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    answers: Mapped[list["LabeledAnswer"]] = relationship(back_populates="answer_set")


class LabeledAnswer(Base):
    __tablename__ = "labeled_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("labeled_answer_sets.id"))
    # Pointer into the private R2 bucket — the gold corpus never lives in this DB or repo.
    raw_ref: Mapped[str] = mapped_column(String(512))
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"))
    human_score: Mapped[float] = mapped_column(Numeric(6, 2))
    # Optional per-step human breakdown keyed by rubric step IDs.
    human_rubric_breakdown: Mapped[dict | None] = mapped_column(JSON)

    answer_set: Mapped[LabeledAnswerSet] = relationship(back_populates="answers")


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    model_name: Mapped[str] = mapped_column(String(128))
    model_version: Mapped[str | None] = mapped_column(String(64))
    rubric_version: Mapped[str] = mapped_column(String(64))
    git_sha: Mapped[str | None] = mapped_column(String(40))
    labeled_set_id: Mapped[int] = mapped_column(ForeignKey("labeled_answer_sets.id"))
    triggered_by: Mapped[BenchmarkTrigger] = mapped_column(
        Enum(BenchmarkTrigger, name="benchmark_trigger")
    )
    status: Mapped[BenchmarkRunStatus] = mapped_column(
        Enum(BenchmarkRunStatus, name="benchmark_run_status"),
        default=BenchmarkRunStatus.running,
    )

    results: Mapped[list["BenchmarkResult"]] = relationship(back_populates="run")
    metrics: Mapped[list["BenchmarkAgreementMetric"]] = relationship(back_populates="run")

    __table_args__ = (Index("ix_benchmark_runs_run_at", "run_at"),)


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("benchmark_runs.id"))
    labeled_answer_id: Mapped[int] = mapped_column(ForeignKey("labeled_answers.id"))
    ai_score: Mapped[float] = mapped_column(Numeric(6, 2))
    human_score: Mapped[float] = mapped_column(Numeric(6, 2))
    abs_diff: Mapped[float] = mapped_column(Numeric(6, 2))
    within_tolerance: Mapped[bool] = mapped_column(Boolean)
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evaluations.id"))

    run: Mapped[BenchmarkRun] = relationship(back_populates="results")

    __table_args__ = (Index("ix_benchmark_results_run", "run_id"),)


class BenchmarkAgreementMetric(Base):
    __tablename__ = "benchmark_agreement_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("benchmark_runs.id"))
    # e.g. "mean_abs_diff", "pct_within_1_5", "pearson_r", "pct_within_1_5_llm_judged_only"
    metric_name: Mapped[str] = mapped_column(String(100))
    metric_value: Mapped[float] = mapped_column(Float)
    n: Mapped[int] = mapped_column(Integer)

    run: Mapped[BenchmarkRun] = relationship(back_populates="metrics")

    __table_args__ = (Index("ix_bam_run_metric", "run_id", "metric_name", unique=True),)


class BenchmarkReport(Base):
    __tablename__ = "benchmark_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("benchmark_runs.id"))
    report_path: Mapped[str] = mapped_column(String(512))  # benchmarks/reports/... in repo
    report_format: Mapped[str] = mapped_column(String(16))  # "md" | "json"
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)  # drives the /trust page
