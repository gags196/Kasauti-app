"""Assembling a paper to sit, and scoring it the way UPSC does.

Everything here operates on questions the corpus already holds — no generation, no
paraphrasing. A learner sitting a Kasauti mock is sitting real UPSC questions with the
official key behind them, which is the only kind of practice this product can honestly
offer today.

Four rules decide what may appear on a paper, and each of them exists because the
alternative would quietly mislead someone:

**Only keyed questions.** A question UPSC dropped carries no correct option. Putting it on
a scored paper would either mark a learner wrong for a question with no right answer, or
silently inflate the denominator.

**Never demo data.** `session='demo'` marks the fabricated development corpus. It is
excluded here as it is everywhere else — a fabricated question inside a scored mock is
the single worst place for demo data to leak.

**Four options, both languages.** The same readiness bar `publish_scan.py` enforces. A
question missing its Hindi twin is not sittable by half the audience.

**A year paper is the printed paper, in printed order.** `year_paper` does not sample or
shuffle: it is 2024 as 2024 was, so a score means what a score meant that morning.
"""

import random
from dataclasses import dataclass

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import (
    Paper,
    Question,
    QuestionOption,
    QuestionTopicMap,
    Topic,
)
from kasauti_api.db.models.practice import (
    NEGATIVE_MARKING_FRACTION,
    PracticeMode,
    PracticeSession,
    QuestionAttempt,
)
from kasauti_api.db.models.questions import QuestionStatus
from kasauti_api.domain.intelligence.scope import topic_match

# UPSC Prelims Paper 1: 100 questions in 120 minutes. A drill defaults shorter because a
# learner drilling one topic is checking recall, not rehearsing stamina.
FULL_MOCK_QUESTIONS = 100
FULL_MOCK_SECONDS = 120 * 60
DRILL_DEFAULT_QUESTIONS = 20
# The same 72 seconds a question gets in the real paper.
SECONDS_PER_QUESTION = FULL_MOCK_SECONDS / FULL_MOCK_QUESTIONS

# Both Prelims papers run two hours, but Paper II asks 80 items where Paper I asks 100,
# so a CSAT item is worth 90 seconds, not 72. Pacing one paper with the other's figure
# would hand a CSAT sitter 96 minutes for a two-hour paper and quietly train the wrong
# rhythm, which is the one thing a timed mock exists to train.
SECONDS_PER_QUESTION_BY_PAPER = {
    "prelims-gs1": 72.0,
    "prelims-gs2": 90.0,
}

# Paper II does not rank; it qualifies, at 33% of its 200 marks. A scorecard that
# reported 120/200 without saying 66 was the line would be describing the wrong exam.
QUALIFYING_FRACTION_BY_PAPER = {
    "prelims-gs2": 0.33,
}

# Which paper a sitting is assembled from when the caller does not say. A "year paper"
# means *one* printed booklet: once a second paper shares a year, selecting by year alone
# silently returns both, so 2026 would hand a learner a 180-question sitting with two
# questions numbered 1. Defaulting rather than requiring keeps every existing caller and
# every stored session unchanged, since Paper I was the only paper until now.
DEFAULT_PAPER_CODE = "prelims-gs1"


@dataclass(frozen=True)
class ScoreCard:
    correct: int
    wrong: int
    skipped: int
    unkeyed: int
    score: float
    max_score: float

    @property
    def accuracy(self) -> float:
        attempted = self.correct + self.wrong
        return self.correct / attempted if attempted else 0.0


def sittable_questions() -> Select:
    """Published, keyed, four-option, bilingual, non-demo questions.

    Returned as a `Select` of ids so callers compose it into their own filters rather
    than each re-deriving what "fit to sit" means.
    """
    keyed = (
        select(QuestionOption.question_id)
        .where(QuestionOption.is_correct.is_(True))
        .subquery()
    )
    four_options = (
        select(QuestionOption.question_id)
        .group_by(QuestionOption.question_id)
        .having(func.count() == 4)
        .subquery()
    )
    return (
        select(Question.id)
        .where(
            Question.status == QuestionStatus.published,
            # Demo questions are fabricated. They may never reach a scored paper.
            (Question.session.is_(None)) | (Question.session != "demo"),
            Question.question_text_en.is_not(None),
            Question.question_text_hi.is_not(None),
            Question.id.in_(select(keyed.c.question_id)),
            Question.id.in_(select(four_options.c.question_id)),
        )
    )


async def paper_code_of(session: AsyncSession, question_ids: list[int]) -> str | None:
    """Which paper an assembled set of questions came from, or None if it is mixed.

    A topic drill can legitimately straddle papers; when it does, neither paper's pacing
    or qualifying rule applies and the caller falls back to the generic figures.
    """
    if not question_ids:
        return None
    codes = set(
        (
            await session.execute(
                select(Paper.code)
                .join(Question, Question.paper_id == Paper.id)
                .where(Question.id.in_(question_ids))
                .distinct()
            )
        ).scalars()
    )
    return codes.pop() if len(codes) == 1 else None


def seconds_per_question(paper_code: str | None) -> float:
    return SECONDS_PER_QUESTION_BY_PAPER.get(paper_code or "", SECONDS_PER_QUESTION)


def qualifying_score(paper_code: str | None, *, question_count: int, marks: float) -> float | None:
    """The mark a qualifying paper must be cleared at, or None if it ranks instead."""
    fraction = QUALIFYING_FRACTION_BY_PAPER.get(paper_code or "")
    if fraction is None:
        return None
    return round(question_count * marks * fraction, 2)


async def available_years(session: AsyncSession, *, paper_code: str | None = None) -> list[int]:
    """Years with a full sittable paper behind them, newest first."""
    stmt = (
        select(Question.year, func.count(Question.id))
        .where(Question.id.in_(sittable_questions()))
        .group_by(Question.year)
        .order_by(Question.year.desc())
    )
    if paper_code:
        stmt = stmt.join(Paper, Paper.id == Question.paper_id).where(
            Paper.code == paper_code
        )
    return [year for year, count in (await session.execute(stmt)).all() if count >= 10]


async def assemble(
    session: AsyncSession,
    *,
    mode: PracticeMode,
    year: int | None = None,
    topic_path: str | None = None,
    count: int | None = None,
    seed: int | None = None,
    paper_code: str | None = None,
) -> list[int]:
    """The question ids for one paper, in the order they will be presented.

    `paper_code` scopes the two modes that select by year or at random. A topic drill
    needs no such scoping: the topic trees are disjoint, so `csat.comprehension` can only
    ever draw Paper II items and `gs2.constitution` can only ever draw Paper I ones.
    """
    base = sittable_questions()
    paper_code = paper_code or DEFAULT_PAPER_CODE
    from_paper = Question.paper_id.in_(select(Paper.id).where(Paper.code == paper_code))

    if mode is PracticeMode.year_paper:
        if year is None:
            raise ValueError("year_paper needs a year")
        rows = (
            await session.execute(
                select(Question.id, Question.question_number)
                .where(Question.id.in_(base), Question.year == year, from_paper)
            )
        ).all()
        # Question numbers are strings ("7", "100"); sort them as the paper prints them.
        return [qid for qid, _ in sorted(rows, key=lambda r: _as_number(r[1]))]

    if mode is PracticeMode.topic_drill:
        if not topic_path:
            raise ValueError("topic_drill needs a topic_path")
        stmt = (
            select(Question.id)
            .join(QuestionTopicMap, QuestionTopicMap.question_id == Question.id)
            .join(Topic, Topic.id == QuestionTopicMap.topic_id)
            .where(and_(Question.id.in_(base), topic_match(topic_path, "subtree")))
            .distinct()
        )
        wanted = count or DRILL_DEFAULT_QUESTIONS
    else:  # full_mock — sampled across every year of one paper
        stmt = select(Question.id).where(Question.id.in_(base), from_paper)
        wanted = count or FULL_MOCK_QUESTIONS

    ids = list((await session.execute(stmt)).scalars().all())
    # Seeded shuffle in Python rather than ORDER BY random(): the seed is stored with the
    # session in the frozen `question_ids`, so a paper is reproducible, and the sample is
    # not re-drawn if the query is ever re-run.
    random.Random(seed).shuffle(ids)
    return ids[:wanted]


def _as_number(question_number: str) -> tuple[int, str]:
    """Sort "7" before "10", and keep anything non-numeric in a stable place after them."""
    digits = "".join(c for c in question_number if c.isdigit())
    return (int(digits) if digits else 10**6, question_number)


async def correct_labels(
    session: AsyncSession, question_ids: list[int]
) -> dict[int, str]:
    """The official answer for each question, from the loaded key and nowhere else."""
    if not question_ids:
        return {}
    rows = (
        await session.execute(
            select(QuestionOption.question_id, QuestionOption.option_label).where(
                QuestionOption.question_id.in_(question_ids),
                QuestionOption.is_correct.is_(True),
            )
        )
    ).all()
    return {qid: label for qid, label in rows}


def score_attempts(
    attempts: list[QuestionAttempt],
    *,
    question_count: int,
    marks_per_question: float,
    negative_marking: bool,
) -> ScoreCard:
    """UPSC's arithmetic: full marks for a correct answer, a third off for a wrong one,
    nothing either way for a blank.

    `question_count` is the whole paper, not the number of rows: a learner who never
    touched the last forty questions skipped them, and the scorecard must say so.
    """
    correct = sum(1 for a in attempts if a.is_correct is True)
    wrong = sum(
        1 for a in attempts if a.is_correct is False and a.selected_label is not None
    )
    unkeyed = sum(1 for a in attempts if a.is_correct is None and a.selected_label)
    answered = sum(1 for a in attempts if a.selected_label is not None)
    penalty = marks_per_question * NEGATIVE_MARKING_FRACTION if negative_marking else 0.0
    return ScoreCard(
        correct=correct,
        wrong=wrong,
        skipped=question_count - answered,
        unkeyed=unkeyed,
        score=round(correct * marks_per_question - wrong * penalty, 2),
        max_score=round(question_count * marks_per_question, 2),
    )


async def finalise(
    session: AsyncSession, practice: PracticeSession
) -> ScoreCard:
    """Freeze each attempt's verdict against the key, then score the paper.

    `is_correct` is written onto the attempts here rather than computed on every read.
    An answer key can be corrected later — 2024 alone had three questions dropped after
    publication — and a score a learner has already seen must not silently change.
    """
    attempts = (
        (
            await session.execute(
                select(QuestionAttempt).where(
                    QuestionAttempt.session_id == practice.id
                )
            )
        )
        .scalars()
        .all()
    )
    keys = await correct_labels(session, list(practice.question_ids))
    for attempt in attempts:
        if attempt.selected_label is None:
            attempt.is_correct = None
            continue
        official = keys.get(attempt.question_id)
        attempt.is_correct = None if official is None else attempt.selected_label == official

    return score_attempts(
        list(attempts),
        question_count=len(practice.question_ids),
        marks_per_question=practice.marks_per_question,
        negative_marking=practice.negative_marking,
    )
