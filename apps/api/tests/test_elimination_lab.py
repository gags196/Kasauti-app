"""The Elimination Lab endpoints, against local Postgres.

Two properties are worth a database test rather than a synthetic one, because both are
about what a learner ends up seeing:

- a firing never arrives without the rule's measured verdict attached, and
- an outcome is computed from the *answer key*, so a rule that fires on a true statement
  and tells the candidate to strike it is reported as having misled them.

The local DB is shared with real ingested papers, so this test inserts its own question
and deletes only that.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import Exam, Paper, Question, QuestionOption
from kasauti_api.db.models.questions import QuestionLanguage, QuestionStatus
from kasauti_api.domain.intelligence.lab import clear_cache
from kasauti_api.main import app
from sqlalchemy import delete, select

STEM = """Consider the following statements:
1. The scheme is available only to citizens above the age of sixty.
2. Some beneficiaries may receive an additional allowance.
Which of the statements given above is/are correct?
"""


@pytest.mark.asyncio
async def test_elimination_lab_reports_outcomes_against_the_key():
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

        question = Question(
            exam_id=exam.id, paper_id=paper.id, year=2024, question_number="901",
            marks=2, language=QuestionLanguage.bilingual,
            question_text_en=STEM,
            question_text_hi="निम्नलिखित कथनों पर विचार कीजिए:",
            status=QuestionStatus.published,
        )
        session.add(question)
        await session.flush()
        # Key = "2 only": statement 1 (carrying "only", which the document says means
        # false) is indeed false, and statement 2 (carrying "Some", which the document
        # says means true) is indeed true. One rule helps, the other helps too — the
        # point of the assertions below is that both are scored against the key.
        session.add_all([
            QuestionOption(question_id=question.id, option_label="A",
                           option_text_en="1 only", is_correct=False),
            QuestionOption(question_id=question.id, option_label="B",
                           option_text_en="2 only", is_correct=True),
            QuestionOption(question_id=question.id, option_label="C",
                           option_text_en="Both 1 and 2", is_correct=False),
            QuestionOption(question_id=question.id, option_label="D",
                           option_text_en="Neither 1 nor 2", is_correct=False),
        ])
        await session.commit()
        question_id = question.id

    clear_cache()  # the corpus just changed; the memo is keyed on its size
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get(f"/api/v1/pyq/questions/{question_id}/elimination")
            assert r.status_code == 200
            body = r.json()
            assert body["decodable"] is True
            assert body["skipped_reason"] is None
            truth = {s["index"]: s["is_true"] for s in body["statements"]}
            assert truth == {1: False, 2: True}

            by_rule = {f["rule_key"]: f for f in body["firings"]}
            extreme = by_rule["extreme_modifier"]
            assert extreme["statement_index"] == 1
            assert extreme["advice"] == "eliminate"
            assert extreme["outcome"] == "helped"
            # The measurement travels with the firing — this is the whole feature.
            assert extreme["measured_verdict"] in {
                "signal", "inverse_signal", "noise", "underpowered"
            }
            assert extreme["measured_n"] > 0

            moderate = by_rule["moderate_modifier"]
            assert moderate["statement_index"] == 2
            assert moderate["advice"] == "keep"
            assert moderate["outcome"] == "helped"

            assert body["helped"] >= 2
            assert body["helped"] + body["misled"] == len(body["firings"])

            r = await client.get("/api/v1/pyq/questions/999999999/elimination")
            assert r.status_code == 404

            r = await client.get("/api/v1/pyq/elimination/rules")
            assert r.status_code == 200
            rules = {row["key"]: row for row in r.json()}
            assert "extreme_modifier" in rules
            assert rules["extreme_modifier"]["docx_claim"].startswith("~1% to 5%")
            # Every rule carries a human-readable verdict, so a UI cannot show a rate
            # without the judgement that goes with it.
            assert all(row["verdict_label"] for row in rules.values())
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(QuestionOption).where(QuestionOption.question_id == question_id)
            )
            await session.execute(delete(Question).where(Question.id == question_id))
            await session.commit()
        clear_cache()


@pytest.mark.asyncio
async def test_a_question_the_key_cannot_decode_says_why():
    """About half the corpus prints no numbered statements. The lab must name the
    reason rather than return an empty analysis that reads like 'no rules fired'."""
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
        question = Question(
            exam_id=exam.id, paper_id=paper.id, year=2024, question_number="902",
            marks=2, language=QuestionLanguage.bilingual,
            question_text_en="Which one of the following is the capital of Nagaland?",
            question_text_hi="निम्नलिखित में से कौन नागालैंड की राजधानी है?",
            status=QuestionStatus.published,
        )
        session.add(question)
        await session.flush()
        session.add_all([
            QuestionOption(question_id=question.id, option_label=label,
                           option_text_en=text, is_correct=(label == "A"))
            for label, text in [("A", "Kohima"), ("B", "Imphal"),
                                ("C", "Aizawl"), ("D", "Itanagar")]
        ])
        await session.commit()
        question_id = question.id

    clear_cache()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get(f"/api/v1/pyq/questions/{question_id}/elimination")
            assert r.status_code == 200
            body = r.json()
            assert body["decodable"] is False
            assert body["skipped_reason"] == "no numbered statements"
            assert body["statements"] == []
            assert body["firings"] == []
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(QuestionOption).where(QuestionOption.question_id == question_id)
            )
            await session.execute(delete(Question).where(Question.id == question_id))
            await session.commit()
        clear_cache()
