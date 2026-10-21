"""Sitting a paper, and what the learner's own record says afterwards.

The single rule that shapes every response here: **an unsubmitted paper never carries the
answer.** `is_correct` is stripped from options until the session is submitted, because
the API is the only thing standing between a learner and their own answer key. A UI that
merely hides the field is one devtools panel away from being useless.

The second rule: this is the *learner's* data. Every query filters on the signed-in
user's id, and a session belonging to someone else is a 404 rather than a 403 — there is
no reason to confirm that another person's session exists.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kasauti_api.api.v1.auth import current_user
from kasauti_api.db.base import get_session
from kasauti_api.db.models import (
    Paper,
    Question,
    QuestionTopicMap,
    Topic,
    User,
)
from kasauti_api.db.models.practice import (
    PracticeMode,
    PracticeSession,
    QuestionAttempt,
)
from kasauti_api.domain.practice.assembly import (
    DEFAULT_PAPER_CODE,
    DRILL_DEFAULT_QUESTIONS,
    FULL_MOCK_QUESTIONS,
    FULL_MOCK_SECONDS,
    assemble,
    available_years,
    finalise,
    paper_code_of,
    qualifying_score,
    seconds_per_question,
)

router = APIRouter(prefix="/api/v1/practice", tags=["practice"])

# A weak topic needs enough attempts to be a signal rather than a bad afternoon.
MIN_ATTEMPTS_FOR_WEAK_TOPIC = 4


class StartSessionIn(BaseModel):
    mode: Literal["year_paper", "full_mock", "topic_drill"]
    # Which printed paper to sit. Only meaningful for year_paper and full_mock — a topic
    # drill is already scoped by its topic tree.
    paper_code: str | None = None
    year: int | None = None
    topic_path: str | None = None
    count: int | None = Field(default=None, ge=5, le=100)


class PracticeOptionOut(BaseModel):
    label: str
    text_en: str | None
    text_hi: str | None
    # Present only once the paper is submitted. Before that it is None for every option,
    # not merely for the wrong ones — the shape of the response cannot leak the answer.
    is_correct: bool | None


class PracticeStimulusOut(BaseModel):
    """The passage or shared directions block an item is answered from.

    Carries no answer information at any point, so unlike the option flags it is sent
    identically before and after submission — a learner sitting a comprehension item
    cannot answer it without the passage.
    """

    id: int
    kind: str
    text_en: str | None
    text_hi: str | None


class PracticeQuestionOut(BaseModel):
    id: int
    index: int
    year: int
    question_number: str
    text_en: str | None
    text_hi: str | None
    tables: list[dict]
    stimulus: PracticeStimulusOut | None
    options: list[PracticeOptionOut]
    selected_label: str | None
    # Only after submission.
    correct_label: str | None
    is_correct: bool | None
    topic_paths: list[str]


class SessionOut(BaseModel):
    id: uuid.UUID
    mode: str
    year: int | None
    topic_path: str | None
    question_count: int
    duration_seconds: int | None
    marks_per_question: float
    negative_marking: bool
    started_at: str
    submitted_at: str | None
    correct_count: int | None
    wrong_count: int | None
    skipped_count: int | None
    unkeyed_count: int | None
    score: float | None
    max_score: float | None
    # Set only for a qualifying paper (Prelims Paper II). NULL means the paper ranks.
    qualifying_score: float | None
    qualified: bool | None


class SessionDetailOut(SessionOut):
    questions: list[PracticeQuestionOut]


class AnswerIn(BaseModel):
    # None means "cleared" — the learner unselected. Under negative marking that is a
    # real decision, so it is stored rather than treated as no answer at all.
    selected_label: str | None = Field(default=None, max_length=4)
    seconds_taken: int | None = Field(default=None, ge=0, le=60 * 60 * 6)


class TopicPerformanceOut(BaseModel):
    topic_id: int
    path: str
    name_en: str
    name_hi: str
    attempted: int
    correct: int
    accuracy: float


class PerformanceOut(BaseModel):
    """The learner's own record. Deliberately small: counts, accuracy, weak topics.

    No streaks, no XP, no rank. Those are engagement mechanics, and this product has not
    earned them yet — what it can honestly show is what you got wrong and where."""

    sessions: int
    submitted_sessions: int
    questions_attempted: int
    correct: int
    accuracy: float
    weak_topics: list[TopicPerformanceOut]
    strong_topics: list[TopicPerformanceOut]
    recent_sessions: list[SessionOut]


class PaperOptionOut(BaseModel):
    code: str
    name_en: str
    name_hi: str
    years: list[int]
    qualifying: bool


class StartOptionsOut(BaseModel):
    # Kept for the default paper so an older client keeps working unchanged.
    years: list[int]
    papers: list[PaperOptionOut]
    full_mock_questions: int
    full_mock_seconds: int
    drill_default_questions: int


def _session_out(practice: PracticeSession) -> SessionOut:
    return SessionOut(
        id=practice.id,
        mode=practice.mode.value,
        year=practice.year,
        topic_path=practice.topic_path,
        question_count=len(practice.question_ids),
        duration_seconds=practice.duration_seconds,
        marks_per_question=practice.marks_per_question,
        negative_marking=practice.negative_marking,
        started_at=practice.started_at.isoformat(),
        submitted_at=practice.submitted_at.isoformat() if practice.submitted_at else None,
        correct_count=practice.correct_count,
        wrong_count=practice.wrong_count,
        skipped_count=practice.skipped_count,
        unkeyed_count=practice.unkeyed_count,
        score=practice.score,
        max_score=practice.max_score,
        qualifying_score=practice.qualifying_score,
        qualified=(
            practice.score >= practice.qualifying_score
            if practice.qualifying_score is not None and practice.score is not None
            else None
        ),
    )


async def _owned_session(
    session: AsyncSession, session_id: uuid.UUID, user: User
) -> PracticeSession:
    practice = (
        await session.execute(
            select(PracticeSession).where(
                PracticeSession.id == session_id,
                PracticeSession.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    # 404, not 403: someone else's session should not be confirmed to exist.
    if practice is None:
        raise HTTPException(404, "Session not found")
    return practice


@router.get("/options", response_model=StartOptionsOut)
async def start_options(
    session: AsyncSession = Depends(get_session),
) -> StartOptionsOut:
    """What can be sat right now — the years with a full keyed paper behind them."""
    papers = []
    for paper in (
        await session.execute(select(Paper).order_by(Paper.code))
    ).scalars():
        years = await available_years(session, paper_code=paper.code)
        if years:
            papers.append(
                PaperOptionOut(
                    code=paper.code,
                    name_en=paper.name_en,
                    name_hi=paper.name_hi,
                    years=years,
                    qualifying=qualifying_score(paper.code, question_count=1, marks=1)
                    is not None,
                )
            )
    return StartOptionsOut(
        years=await available_years(session, paper_code=DEFAULT_PAPER_CODE),
        papers=papers,
        full_mock_questions=FULL_MOCK_QUESTIONS,
        full_mock_seconds=FULL_MOCK_SECONDS,
        drill_default_questions=DRILL_DEFAULT_QUESTIONS,
    )


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def start_session(
    payload: StartSessionIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> SessionOut:
    mode = PracticeMode(payload.mode)
    try:
        question_ids = await assemble(
            session,
            mode=mode,
            year=payload.year,
            topic_path=payload.topic_path,
            count=payload.count,
            paper_code=payload.paper_code,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    if len(question_ids) < 5:
        raise HTTPException(
            409,
            "Not enough keyed questions in the corpus for that selection yet.",
        )

    marks = await _marks_per_question(session, question_ids)
    paper_code = await paper_code_of(session, question_ids)
    practice = PracticeSession(
        user_id=user.id,
        mode=mode,
        year=payload.year,
        topic_path=payload.topic_path,
        question_ids=question_ids,
        duration_seconds=int(len(question_ids) * seconds_per_question(paper_code)),
        marks_per_question=marks,
        negative_marking=True,
        qualifying_score=qualifying_score(
            paper_code, question_count=len(question_ids), marks=marks
        ),
    )
    session.add(practice)
    await session.commit()
    await session.refresh(practice)
    return _session_out(practice)


async def _marks_per_question(session: AsyncSession, question_ids: list[int]) -> float:
    """The paper's own marks figure, not a constant.

    Extraction leaves `marks` NULL and `publish_scan.py --marks` fills it from the
    booklet's instruction page, so the corpus already knows what a question is worth.
    Hardcoding 2.0 here would quietly break the day Paper 2 (which is not 2.0) lands."""
    value = (
        await session.execute(
            select(func.avg(Question.marks)).where(Question.id.in_(question_ids))
        )
    ).scalar()
    return float(value) if value else 2.0


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    limit: int = Query(default=20, le=100),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> list[SessionOut]:
    rows = (
        (
            await session.execute(
                select(PracticeSession)
                .where(PracticeSession.user_id == user.id)
                .order_by(PracticeSession.started_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_session_out(row) for row in rows]


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
async def get_practice_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> SessionDetailOut:
    practice = await _owned_session(session, session_id, user)
    revealed = practice.is_submitted

    questions = {
        q.id: q
        for q in (
            (
                await session.execute(
                    select(Question)
                    .options(
                        selectinload(Question.options),
                        selectinload(Question.stimulus),
                        selectinload(Question.topic_maps).selectinload(
                            QuestionTopicMap.topic
                        ),
                    )
                    .where(Question.id.in_(practice.question_ids))
                )
            )
            .scalars()
            .all()
        )
    }
    attempts = {
        a.question_id: a
        for a in (
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
    }

    out: list[PracticeQuestionOut] = []
    for index, question_id in enumerate(practice.question_ids, start=1):
        question = questions.get(question_id)
        if question is None:
            continue
        attempt = attempts.get(question_id)
        options = sorted(question.options, key=lambda o: o.option_label)
        correct_label = next(
            (o.option_label for o in options if o.is_correct), None
        )
        out.append(
            PracticeQuestionOut(
                id=question.id,
                index=index,
                year=question.year,
                question_number=question.question_number,
                text_en=question.question_text_en,
                text_hi=question.question_text_hi,
                tables=question.tables or [],
                stimulus=(
                    PracticeStimulusOut(
                        id=question.stimulus.id,
                        kind=question.stimulus.kind.value,
                        text_en=question.stimulus.text_en,
                        text_hi=question.stimulus.text_hi,
                    )
                    if question.stimulus is not None
                    else None
                ),
                options=[
                    PracticeOptionOut(
                        label=o.option_label,
                        text_en=o.option_text_en,
                        text_hi=o.option_text_hi,
                        # The whole point of this endpoint's design.
                        is_correct=o.is_correct if revealed else None,
                    )
                    for o in options
                ],
                selected_label=attempt.selected_label if attempt else None,
                correct_label=correct_label if revealed else None,
                is_correct=attempt.is_correct if (revealed and attempt) else None,
                topic_paths=[
                    str(m.topic.path) for m in question.topic_maps if m.topic is not None
                ],
            )
        )

    detail = _session_out(practice).model_dump()
    return SessionDetailOut(**detail, questions=out)


@router.put("/sessions/{session_id}/answers/{question_id}", status_code=204)
async def save_answer(
    session_id: uuid.UUID,
    question_id: int,
    payload: AnswerIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> None:
    """Record (or replace) one answer. Idempotent — changing your mind is normal."""
    practice = await _owned_session(session, session_id, user)
    if practice.is_submitted:
        raise HTTPException(409, "This paper has already been submitted.")
    if question_id not in practice.question_ids:
        raise HTTPException(404, "That question is not on this paper.")

    attempt = (
        await session.execute(
            select(QuestionAttempt).where(
                QuestionAttempt.session_id == practice.id,
                QuestionAttempt.question_id == question_id,
            )
        )
    ).scalar_one_or_none()
    if attempt is None:
        attempt = QuestionAttempt(
            user_id=user.id, question_id=question_id, session_id=practice.id
        )
        session.add(attempt)
    attempt.selected_label = payload.selected_label
    if payload.seconds_taken is not None:
        attempt.seconds_taken = payload.seconds_taken
    # is_correct stays NULL until submission: nothing here consults the answer key, so a
    # timing attack on this endpoint cannot reveal it either.
    await session.commit()


@router.post("/sessions/{session_id}/submit", response_model=SessionOut)
async def submit_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> SessionOut:
    practice = await _owned_session(session, session_id, user)
    if practice.is_submitted:
        # Submitting twice returns the first result rather than rescoring. A score the
        # learner has seen is a fact about that sitting.
        return _session_out(practice)

    card = await finalise(session, practice)
    practice.submitted_at = datetime.now(UTC)
    practice.correct_count = card.correct
    practice.wrong_count = card.wrong
    practice.skipped_count = card.skipped
    practice.unkeyed_count = card.unkeyed
    practice.score = card.score
    practice.max_score = card.max_score
    await session.commit()
    await session.refresh(practice)
    return _session_out(practice)


@router.get("/performance", response_model=PerformanceOut)
async def performance(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> PerformanceOut:
    """Weak areas, from this learner's own attempts.

    Only submitted sessions count: an abandoned paper's blanks are not evidence of
    anything, and counting them would make every learner look weak everywhere.
    """
    totals = (
        await session.execute(
            select(
                func.count(QuestionAttempt.id),
                func.count(QuestionAttempt.id).filter(
                    QuestionAttempt.is_correct.is_(True)
                ),
            ).where(QuestionAttempt.user_id == user.id)
        )
    ).one()
    attempted, correct = totals[0] or 0, totals[1] or 0

    session_counts = (
        await session.execute(
            select(
                func.count(PracticeSession.id),
                func.count(PracticeSession.id).filter(
                    PracticeSession.submitted_at.is_not(None)
                ),
            ).where(PracticeSession.user_id == user.id)
        )
    ).one()

    # Accuracy per topic, over attempts where the learner actually chose an option.
    graded = func.count(QuestionAttempt.id).filter(
        QuestionAttempt.is_correct.is_not(None)
    )
    got_right = func.count(QuestionAttempt.id).filter(QuestionAttempt.is_correct.is_(True))
    topic_rows = (
        await session.execute(
            select(
                Topic.id,
                cast(Topic.path, String),
                Topic.name_en,
                Topic.name_hi,
                graded,
                got_right,
            )
            .join(QuestionTopicMap, QuestionTopicMap.topic_id == Topic.id)
            .join(
                QuestionAttempt,
                QuestionAttempt.question_id == QuestionTopicMap.question_id,
            )
            .where(QuestionAttempt.user_id == user.id)
            .group_by(Topic.id)
            .having(graded >= MIN_ATTEMPTS_FOR_WEAK_TOPIC)
        )
    ).all()

    scored = [
        TopicPerformanceOut(
            topic_id=row[0],
            path=row[1],
            name_en=row[2],
            name_hi=row[3],
            attempted=row[4],
            correct=row[5],
            accuracy=row[5] / row[4] if row[4] else 0.0,
        )
        for row in topic_rows
    ]
    scored.sort(key=lambda t: (t.accuracy, -t.attempted))

    recent = (
        (
            await session.execute(
                select(PracticeSession)
                .where(PracticeSession.user_id == user.id)
                .order_by(PracticeSession.started_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )

    return PerformanceOut(
        sessions=session_counts[0] or 0,
        submitted_sessions=session_counts[1] or 0,
        questions_attempted=attempted,
        correct=correct,
        accuracy=correct / attempted if attempted else 0.0,
        weak_topics=scored[:8],
        strong_topics=list(reversed(scored[-8:])),
        recent_sessions=[_session_out(row) for row in recent],
    )
