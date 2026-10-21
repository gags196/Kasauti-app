"""Answer-key application against local Postgres.

Correctness enters the system only through this path, so the conservative cases matter
more than the happy one: a dropped question must stay unknown, and a key that names
options the paper does not have must be refused outright.
"""

import pytest
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import Exam, Paper, Question, QuestionOption
from kasauti_api.db.models.questions import QuestionLanguage, QuestionStatus
from kasauti_api.domain.ingestion.answer_key import apply_answer_key
from sqlalchemy import delete, select

YEAR = 1901  # far from any real paper, so this test never collides with real data


async def _make_question(session, paper, number: str, labels=("A", "B", "C", "D")):
    q = Question(
        exam_id=paper.exam_id, paper_id=paper.id, year=YEAR, question_number=number,
        marks=2, language=QuestionLanguage.en,
        question_text_en=f"Test question {number}?", status=QuestionStatus.published,
    )
    session.add(q)
    await session.flush()
    for label in labels:
        session.add(
            QuestionOption(question_id=q.id, option_label=label, option_text_en=label)
        )
    await session.flush()
    return q


async def _correctness(session, question_id: int) -> dict[str, bool | None]:
    rows = (
        await session.execute(
            select(QuestionOption.option_label, QuestionOption.is_correct)
            .where(QuestionOption.question_id == question_id)
        )
    ).all()
    return {label: is_correct for label, is_correct in rows}


@pytest.mark.asyncio
async def test_applies_normal_key_and_leaves_dropped_questions_unknown():
    async with async_session_factory() as session:
        exam = (
            await session.execute(select(Exam).where(Exam.code == "upsc-cse"))
        ).scalar_one_or_none()
        if exam is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
        paper = (
            await session.execute(
                select(Paper).where(Paper.exam_id == exam.id, Paper.code == "prelims-gs1")
            )
        ).scalar_one()

        normal = await _make_question(session, paper, "1")
        dropped = await _make_question(session, paper, "2")
        await session.commit()
        normal_id, dropped_id = normal.id, dropped.id

    try:
        async with async_session_factory() as session:
            paper_id = normal.paper_id
            result = await apply_answer_key(
                session, paper_id=paper_id, year=YEAR,
                # "X" is how UPSC marks a withdrawn question.
                key={"1": "C", "2": "X", "99": "A"},
            )
            await session.commit()

            assert result.applied == 1
            assert result.dropped == ["2"]
            assert result.missing_question == ["99"]
            assert not result.has_integrity_error

            assert await _correctness(session, normal_id) == {
                "A": False, "B": False, "C": True, "D": False
            }
            # The dropped question must stay UNKNOWN, not known-wrong. All-false would
            # assert we know the answer and none of these is it, and would suppress the
            # "answer key pending" state in the UI.
            assert await _correctness(session, dropped_id) == {
                "A": None, "B": None, "C": None, "D": None
            }
    finally:
        await _cleanup([normal_id, dropped_id])


@pytest.mark.asyncio
async def test_label_the_paper_lacks_is_an_integrity_error_and_writes_nothing():
    """A key naming an option the question doesn't have means the wrong booklet series.
    Series have different question orders, so applying it would corrupt everything."""
    async with async_session_factory() as session:
        exam = (
            await session.execute(select(Exam).where(Exam.code == "upsc-cse"))
        ).scalar_one_or_none()
        if exam is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
        paper = (
            await session.execute(
                select(Paper).where(Paper.exam_id == exam.id, Paper.code == "prelims-gs1")
            )
        ).scalar_one()
        # Only three options, but the key will claim "D".
        q = await _make_question(session, paper, "1", labels=("A", "B", "C"))
        await session.commit()
        q_id, paper_id = q.id, paper.id

    try:
        async with async_session_factory() as session:
            result = await apply_answer_key(
                session, paper_id=paper_id, year=YEAR, key={"1": "D"}
            )
            assert result.has_integrity_error
            assert result.unknown_label == [("1", "D")]
            assert result.applied == 0
            await session.rollback()

        async with async_session_factory() as session:
            assert await _correctness(session, q_id) == {"A": None, "B": None, "C": None}
    finally:
        await _cleanup([q_id])


async def _cleanup(question_ids: list[int]) -> None:
    async with async_session_factory() as session:
        await session.execute(
            delete(QuestionOption).where(QuestionOption.question_id.in_(question_ids))
        )
        await session.execute(delete(Question).where(Question.id.in_(question_ids)))
        await session.commit()
