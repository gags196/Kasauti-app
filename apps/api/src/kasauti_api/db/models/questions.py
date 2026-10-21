import enum
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kasauti_api.db.base import Base

if TYPE_CHECKING:
    from kasauti_api.db.models.taxonomy import Topic

EMBEDDING_DIM = 1024  # voyage-multilingual-2


class OcrStatus(enum.Enum):
    pending = "pending"
    extracted = "extracted"
    segmented = "segmented"
    human_review = "human_review"
    published = "published"


class QuestionLanguage(enum.Enum):
    en = "en"
    hi = "hi"
    bilingual = "bilingual"


class QuestionStatus(enum.Enum):
    draft = "draft"
    human_review = "human_review"
    published = "published"


class TaggedBy(enum.Enum):
    model = "model"
    human = "human"


class StimulusKind(enum.Enum):
    """What kind of shared block a stimulus is.

    passage    — the comprehension text a run of items is answered from.
    directions — a shared instruction block, e.g. the data-sufficiency key that
                 defines what (a)-(d) mean for the five items under it.
    figure     — a diagram whose content IS its shape (route-counting grids,
                 growth curves, age-pyramids) with no printed numbers to fall
                 back on as a table. Reuses the shared-block mechanism even
                 though a figure typically serves exactly one question, because
                 the alternative is a new table for something that already
                 generalizes. See `asset_key` below.
    """

    passage = "passage"
    directions = "directions"
    figure = "figure"


class SourceScan(Base):
    __tablename__ = "source_scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id"))
    year: Mapped[int] = mapped_column()
    page_range: Mapped[str | None] = mapped_column(String(64))
    r2_key: Mapped[str] = mapped_column(String(512))
    upload_batch_id: Mapped[str | None] = mapped_column(String(64))
    ocr_status: Mapped[OcrStatus] = mapped_column(
        Enum(OcrStatus, name="ocr_status"), default=OcrStatus.pending
    )
    raw_extraction_json: Mapped[dict | None] = mapped_column(JSON)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    reviewed_by: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    questions: Mapped[list["Question"]] = relationship(back_populates="source_scan")

    __table_args__ = (Index("ix_source_scans_status", "ocr_status"),)


class QuestionStimulus(Base):
    """A block printed once and answered by several items.

    Prelims Paper II (CSAT) prints a comprehension passage above two to five items,
    and prints one option key above a run of data-sufficiency items. Neither belongs
    in any single question's stem: five items would carry five copies of the same
    400-word passage, search would return five near-identical hits for one passage,
    and every corpus statistic that counts text would count it five times.

    Options are NOT stored here even when the paper factors them out. A shared option
    key is per-item semantics printed once for economy, so the four options are copied
    onto each item and the invariant that a scored question holds exactly four options
    survives untouched. A passage is genuinely one object shared by many items, so it
    lives here.
    """

    __tablename__ = "question_stimuli"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"))
    year: Mapped[int] = mapped_column()
    source_scan_id: Mapped[int | None] = mapped_column(ForeignKey("source_scans.id"))
    kind: Mapped[StimulusKind] = mapped_column(Enum(StimulusKind, name="stimulus_kind"))
    # The extractor's own key for this block within one slice ("passage-1"), which is
    # how its items point at it before either has a database id. Unique per scan, so
    # re-running extraction on a slice updates the same rows instead of duplicating them.
    ref: Mapped[str] = mapped_column(String(64))
    text_en: Mapped[str | None] = mapped_column(Text)
    text_hi: Mapped[str | None] = mapped_column(Text)
    # Set only on kind='figure', by scripts/attach_figure.py after a human has cropped
    # the diagram out of the scan — never by extraction. The R2 object key in
    # settings.r2_bucket_question_assets; served to learners via
    # GET /api/v1/pyq/figures/{stimulus_id} rather than a direct R2 link.
    asset_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    questions: Mapped[list["Question"]] = relationship(back_populates="stimulus")

    __table_args__ = (
        Index("ix_question_stimuli_scan_ref", "source_scan_id", "ref", unique=True),
        Index("ix_question_stimuli_paper_year", "paper_id", "year"),
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"))
    year: Mapped[int] = mapped_column()
    session: Mapped[str | None] = mapped_column(String(32))
    question_number: Mapped[str] = mapped_column(String(32))
    marks: Mapped[float | None] = mapped_column(Numeric(6, 2))
    language: Mapped[QuestionLanguage] = mapped_column(
        Enum(QuestionLanguage, name="question_language")
    )
    question_text_en: Mapped[str | None] = mapped_column(Text)
    question_text_hi: Mapped[str | None] = mapped_column(Text)
    question_text_original: Mapped[str | None] = mapped_column(Text)  # as extracted, pre-cleanup
    math_notation_latex: Mapped[str | None] = mapped_column(Text)
    # Tables printed inside the question — "Match List I with List II" and data tables,
    # which appear in most UPSC papers. Stored as the ExtractedTable JSON shape rather
    # than normalised, because shape varies per question and nothing queries inside a
    # single table; flattening them into the text loses the row/column relationship
    # the question is testing.
    # none_as_null matters: plain JSON stores Python None as the JSON literal `null`,
    # which is NOT SQL NULL, so `WHERE tables IS NOT NULL` would match rows that have
    # no tables. This keeps exactly two states: SQL NULL, or a JSON array.
    tables: Mapped[list | None] = mapped_column(JSON(none_as_null=True))
    source_scan_id: Mapped[int | None] = mapped_column(ForeignKey("source_scans.id"))
    # NULL for every question that stands alone, which is all of Paper I.
    stimulus_id: Mapped[int | None] = mapped_column(ForeignKey("question_stimuli.id"))
    status: Mapped[QuestionStatus] = mapped_column(
        Enum(QuestionStatus, name="question_status"), default=QuestionStatus.draft
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source_scan: Mapped[SourceScan | None] = relationship(back_populates="questions")
    stimulus: Mapped[QuestionStimulus | None] = relationship(back_populates="questions")
    topic_maps: Mapped[list["QuestionTopicMap"]] = relationship(back_populates="question")
    embeddings: Mapped[list["QuestionEmbedding"]] = relationship(back_populates="question")
    options: Mapped[list["QuestionOption"]] = relationship(back_populates="question")

    __table_args__ = (
        Index("ix_questions_paper_year", "paper_id", "year"),
        Index("ix_questions_status", "status"),
    )


class QuestionOption(Base):
    """Prelims MCQ options. is_correct stays NULL until the official answer key
    is loaded (scripts/load_answer_key.py) — option-pattern analysis (Feature A2)
    depends on it."""

    __tablename__ = "question_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    option_label: Mapped[str] = mapped_column(String(4))  # "A" | "B" | "C" | "D"
    option_text_en: Mapped[str | None] = mapped_column(Text)
    option_text_hi: Mapped[str | None] = mapped_column(Text)
    is_correct: Mapped[bool | None] = mapped_column()

    question: Mapped[Question] = relationship(back_populates="options")

    __table_args__ = (
        Index("ix_question_options_question", "question_id", "option_label", unique=True),
    )


class QuestionTopicMap(Base):
    __tablename__ = "question_topic_map"

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), primary_key=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    tagged_by: Mapped[TaggedBy] = mapped_column(Enum(TaggedBy, name="tagged_by"))

    question: Mapped[Question] = relationship(back_populates="topic_maps")
    topic: Mapped["Topic"] = relationship()

    __table_args__ = (Index("ix_qtm_topic", "topic_id"),)


class QuestionEmbedding(Base):
    __tablename__ = "question_embeddings"

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    lang: Mapped[str] = mapped_column(String(2), primary_key=True)  # "en" | "hi"
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    question: Mapped[Question] = relationship(back_populates="embeddings")

    __table_args__ = (
        Index(
            "ix_question_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
