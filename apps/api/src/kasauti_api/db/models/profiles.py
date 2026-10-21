"""Per-question profile: what kind of question it is, and how its options are built.

One row per question, holding two blocks that are written by two different processes
and trusted differently.

**Deterministic** — statement counts, option archetype, the option geometry the A2
pattern analysis runs on. Pure Python over text already in the database, rebuilt by
`scripts/derive_question_facts.py` in seconds. `derived_rev` is bumped whenever a rule
changes, so `WHERE derived_rev <> CURRENT` is a queryable staleness signal rather than a
thing anyone has to remember.

**Classified** — format, cognitive depth, and whether the item was anchored to current
affairs. These come from a batched LLM pass and stay NULL until it reaches the question.
NULL means "not classified yet", which is honest; it is never backfilled with a guess.

Storing both together is deliberate. The deterministic block alone answers "what question
types are asked" and "how are options constructed" with no model calls at all, and it
gives the regex-versus-model disagreement (`format IS DISTINCT FROM regex_format`)
somewhere to live with a record of what the regex said at the time.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kasauti_api.db.base import Base
from kasauti_api.db.models.questions import Question, TaggedBy


class QuestionFormat(enum.Enum):
    """How the item is put to the candidate.

    `how_many_correct` is deliberately separate from `statement_evaluation` even though
    both print a numbered list: the count form gives no partial credit to eliminating one
    statement, and it did not exist in Prelims before 2022.
    """

    statement_evaluation = "statement_evaluation"
    how_many_correct = "how_many_correct"
    pairs_matched = "pairs_matched"
    match_the_following = "match_the_following"
    assertion_reason = "assertion_reason"
    chronological_order = "chronological_order"
    single_fact = "single_fact"
    passage_based = "passage_based"
    other = "other"


class QuestionDepth(enum.Enum):
    """What the candidate has to *do* — not how hard the question is.

    There is deliberately no difficulty field anywhere in this schema. Difficulty needs
    attempt data, and we have none; an assigned difficulty would be an opinion with a
    number on it, and it would end up on a chart. Depth is visible in the stem.
    """

    recall = "recall"
    comprehension = "comprehension"
    application = "application"
    analysis = "analysis"


class OptionArchetype(enum.Enum):
    """The shape of the option set, which strongly conditions the option statistics.

    `subset_of_numbered` ("1 only / 2 only / Both 1 and 2 / Neither 1 nor 2") matters
    most: "Both 1 and 2" is mechanically the longest string in that family, so any
    "the longest option is correct" statistic must be stratified by archetype or it
    measures the printing convention rather than the examiner.
    """

    subset_of_numbered = "subset_of_numbered"
    count_of_correct = "count_of_correct"
    entity_choice = "entity_choice"
    numeric = "numeric"
    ordering = "ordering"
    other = "other"


# Both `format` and `regex_format` are this type. They must share one Enum object, or
# SQLAlchemy emits CREATE TYPE question_format twice and the DDL aborts.
QUESTION_FORMAT_ENUM = Enum(QuestionFormat, name="question_format")


class QuestionProfile(Base):
    __tablename__ = "question_profiles"

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )

    # ---- classified by the batched LLM pass; NULL until it runs ----
    format: Mapped[QuestionFormat | None] = mapped_column(QUESTION_FORMAT_ENUM)
    depth: Mapped[QuestionDepth | None] = mapped_column(
        Enum(QuestionDepth, name="question_depth")
    )
    # Low-trust for older years: for a 2013 item the model is being asked what was in the
    # news in 2012, from a stem alone, with nothing to check against. Useful from ~2020.
    current_affairs_anchored: Mapped[bool | None] = mapped_column(Boolean)
    llm_confidence: Mapped[float | None] = mapped_column(Float)
    model_name: Mapped[str | None] = mapped_column(String(128))
    prompt_ref: Mapped[str | None] = mapped_column(String(256))
    classified_by: Mapped[TaggedBy | None] = mapped_column(
        Enum(TaggedBy, name="tagged_by")
    )
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ---- derived in Python, no LLM; rebuilt whenever derived_rev moves ----
    derived_rev: Mapped[int] = mapped_column(Integer)
    derived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    regex_format: Mapped[QuestionFormat | None] = mapped_column(QUESTION_FORMAT_ENUM)
    statement_count: Mapped[int | None] = mapped_column(Integer)
    option_count: Mapped[int] = mapped_column(Integer)
    option_archetype: Mapped[OptionArchetype | None] = mapped_column(
        Enum(OptionArchetype, name="option_archetype")
    )
    stem_chars_en: Mapped[int | None] = mapped_column(Integer)
    # Never compare this against stem_chars_en: Devanagari tokenizes far denser, so the
    # two are not on the same scale and must never share an axis or be averaged.
    stem_chars_hi: Mapped[int | None] = mapped_column(Integer)
    has_table: Mapped[bool] = mapped_column(Boolean)
    has_all_of_above: Mapped[bool] = mapped_column(Boolean)
    has_none_of_above: Mapped[bool] = mapped_column(Boolean)

    # Denormalised from question_options so every option statistic is a GROUP BY rather
    # than a full-corpus scan. Single writer: scripts/derive_question_facts.py, whose
    # --check mode reports drift after an answer key is loaded or corrected.
    correct_label: Mapped[str | None] = mapped_column(String(4))
    correct_is_longest: Mapped[bool | None] = mapped_column(Boolean)
    # NULL when the top two options tie on length — a tie is not a weak signal, it is
    # the absence of one, and recording False there would invent a finding.
    longest_margin: Mapped[float | None] = mapped_column(Float)
    dated_option_count: Mapped[int] = mapped_column(Integer, default=0)
    dated_correct: Mapped[bool | None] = mapped_column(Boolean)

    question: Mapped[Question] = relationship()

    __table_args__ = (
        Index("ix_question_profiles_format", "format", "depth"),
        Index("ix_question_profiles_archetype", "option_archetype"),
        Index("ix_question_profiles_rev", "derived_rev"),
    )
