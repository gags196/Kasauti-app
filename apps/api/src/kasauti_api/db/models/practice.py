"""What a learner actually did: sat a paper, answered a question, got it wrong.

Everything the product knows today describes the *exam* — which topics are heavy, how
formats drifted, which coaching shortcuts fail. None of it describes the *learner*. These
two tables are the missing half, and every per-user feature (weak areas, adaptive
practice, a leaderboard, a paywall worth paying for) is blocked on them existing.

Three decisions are baked in here rather than left to callers:

**A skipped question is a row, not a missing row.** `selected_label` NULL means the
learner saw it and left it blank, which under UPSC's negative marking is a *deliberate and
often correct* choice. Inferring skips from absent rows would make "attempted 60 of 100"
indistinguishable from "the network dropped 40 saves".

**`is_correct` is copied from the official key at attempt time, never re-derived.**
`question_options.is_correct` comes only from a loaded answer key, and a key can be
corrected later; a past attempt must keep the verdict the learner was actually shown.
NULL means the question carries no key (UPSC dropped it), and a dropped question scores
zero either way — it is never counted as wrong.

**The assembled paper is stored on the session.** `question_ids` freezes the order at
creation, so a learner reloading mid-test sees the same paper in the same order, and a
result page can be rebuilt exactly even after the corpus grows.
"""

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
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kasauti_api.db.base import Base
from kasauti_api.db.models.questions import Question

# UPSC Prelims deducts one third of a question's marks for a wrong answer, and nothing
# for a blank. That ratio is the whole reason skipping is a skill worth practising, so it
# lives here as the scoring rule rather than as a number typed into a UI.
NEGATIVE_MARKING_FRACTION = 1 / 3


class PracticeMode(enum.Enum):
    """How the paper in front of the learner was assembled.

    `year_paper` is the real thing — one printed paper, in its printed order. The other
    two are constructed, and the distinction matters when reading a score: a 62 on the
    2024 paper is comparable to other people's 2024 attempts, and a 62 on a topic drill
    is not comparable to anything.
    """

    year_paper = "year_paper"
    full_mock = "full_mock"
    topic_drill = "topic_drill"


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    mode: Mapped[PracticeMode] = mapped_column(Enum(PracticeMode, name="practice_mode"))
    # Set for year_paper; NULL for the constructed modes.
    year: Mapped[int | None] = mapped_column(Integer)
    topic_path: Mapped[str | None] = mapped_column(String(512))
    # The frozen paper: question ids in the order they are presented.
    question_ids: Mapped[list] = mapped_column(JSON)
    # The allowance shown on the clock. Not enforced server-side — a learner who loses
    # connectivity mid-paper should not lose the paper — but recorded so a result can say
    # whether it was sat under exam conditions.
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    marks_per_question: Mapped[float] = mapped_column(Float, default=2.0)
    negative_marking: Mapped[bool] = mapped_column(Boolean, default=True)
    # Marks needed to qualify, where the paper is a qualifying one. Prelims Paper II is
    # scored out of 200 and 66 of them is the whole result: a candidate on 65 is out of
    # the examination regardless of their Paper I mark. Frozen here rather than computed
    # at read time for the same reason a verdict is — the threshold in force on the day
    # is what the learner was actually sitting against. NULL means the paper ranks rather
    # than qualifies, which is every Paper I attempt.
    qualifying_score: Mapped[float | None] = mapped_column(Float)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # All NULL until submission. Written once, then immutable: a score a learner has seen
    # must not change because an answer key was corrected next month.
    correct_count: Mapped[int | None] = mapped_column(Integer)
    wrong_count: Mapped[int | None] = mapped_column(Integer)
    skipped_count: Mapped[int | None] = mapped_column(Integer)
    unkeyed_count: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    max_score: Mapped[float | None] = mapped_column(Float)

    attempts: Mapped[list["QuestionAttempt"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_practice_sessions_user", "user_id", "started_at"),
        Index("ix_practice_sessions_mode", "mode", "year"),
    )

    @property
    def is_submitted(self) -> bool:
        return self.submitted_at is not None


class QuestionAttempt(Base):
    __tablename__ = "question_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE")
    )
    # NULL means the learner left it blank, which is a real answer under negative marking.
    selected_label: Mapped[str | None] = mapped_column(String(4))
    # Frozen from the official key at submission. NULL = the question carries no key.
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    seconds_taken: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped[PracticeSession | None] = relationship(back_populates="attempts")
    question: Mapped[Question] = relationship()

    __table_args__ = (
        # One attempt per question per session: answering again replaces the answer,
        # exactly as changing your mind on the OMR sheet does.
        Index(
            "ix_question_attempts_session_question",
            "session_id",
            "question_id",
            unique=True,
        ),
        Index("ix_question_attempts_user", "user_id", "created_at"),
        Index("ix_question_attempts_question", "question_id"),
    )
