"""Accounts, sitting a paper, and scoring it — end to end against local Postgres.

Two properties here are the reason this file exists, and neither is cosmetic:

**An unsubmitted paper must not carry the answer.** The API is the only thing between a
learner and their own answer key; a UI that merely hides the field is one devtools panel
away from useless. The test asserts the field is absent for *every* option, not just the
wrong ones, because a response shape that differs between right and wrong leaks the
answer just as surely as the flag would.

**Negative marking is UPSC's arithmetic, not ours.** One third of a question's marks come
off a wrong answer and nothing comes off a blank, which is exactly why skipping is a
skill. A scorecard that quietly treats a blank as wrong would teach the opposite habit.

The local DB is shared with real ingested papers, so this test creates its own user and
deletes only what it created.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import Paper, Question, User
from kasauti_api.db.models.practice import PracticeMode, PracticeSession, QuestionAttempt
from kasauti_api.db.models.questions import QuestionStatus
from kasauti_api.domain.practice.assembly import (
    assemble,
    qualifying_score,
    score_attempts,
    seconds_per_question,
)
from kasauti_api.main import app
from sqlalchemy import delete, select

PASSWORD = "kasauti-test-password"


def _email() -> str:
    # Not a .test/.invalid address: pydantic's EmailStr rejects the reserved TLDs, so a
    # throwaway subdomain of a domain we own is the address a test can actually register.
    return f"test-{uuid.uuid4().hex[:12]}@qa.kasauti.in"


async def _register_and_login(client: AsyncClient) -> tuple[str, str]:
    email = _email()
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Test Aspirant"},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/auth/jwt/login",
        data={"username": email, "password": PASSWORD},
    )
    assert r.status_code == 200, r.text
    return email, r.json()["access_token"]


async def _cleanup(email: str) -> None:
    async with async_session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            return
        await session.execute(
            delete(QuestionAttempt).where(QuestionAttempt.user_id == user.id)
        )
        await session.execute(
            delete(PracticeSession).where(PracticeSession.user_id == user.id)
        )
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


def test_negative_marking_is_upsc_arithmetic():
    """A blank costs nothing; a wrong answer costs a third. Pure function, no DB."""

    class _Attempt:
        def __init__(self, is_correct, selected_label):
            self.is_correct = is_correct
            self.selected_label = selected_label

    attempts = [
        _Attempt(True, "A"),
        _Attempt(True, "B"),
        _Attempt(False, "C"),
        _Attempt(None, None),  # left blank
    ]
    card = score_attempts(
        attempts, question_count=10, marks_per_question=2.0, negative_marking=True
    )
    assert card.correct == 2
    assert card.wrong == 1
    # Six untouched questions plus the one deliberately left blank.
    assert card.skipped == 7
    assert card.score == pytest.approx(2 * 2.0 - 2.0 / 3, abs=0.01)
    assert card.max_score == 20.0
    assert card.accuracy == pytest.approx(2 / 3, abs=0.001)

    lenient = score_attempts(
        attempts, question_count=10, marks_per_question=2.0, negative_marking=False
    )
    assert lenient.score == 4.0


@pytest.mark.asyncio
async def test_sit_a_paper_end_to_end():
    email = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            email, token = await _register_and_login(client)
            auth = {"Authorization": f"Bearer {token}"}

            r = await client.get("/api/v1/users/me", headers=auth)
            assert r.status_code == 200
            assert r.json()["email"] == email

            r = await client.get("/api/v1/practice/options")
            assert r.status_code == 200
            years = r.json()["years"]
            if not years:
                pytest.skip("no keyed papers ingested — nothing sittable")

            r = await client.post(
                "/api/v1/practice/sessions",
                json={"mode": "topic_drill", "topic_path": "gs3.indian_economy",
                      "count": 5},
                headers=auth,
            )
            if r.status_code == 409:
                r = await client.post(
                    "/api/v1/practice/sessions",
                    json={"mode": "full_mock", "count": 5},
                    headers=auth,
                )
            assert r.status_code == 201, r.text
            practice = r.json()
            session_id = practice["id"]
            assert practice["submitted_at"] is None
            assert practice["score"] is None
            assert practice["negative_marking"] is True

            r = await client.get(f"/api/v1/practice/sessions/{session_id}", headers=auth)
            assert r.status_code == 200
            detail = r.json()
            questions = detail["questions"]
            assert len(questions) == practice["question_count"]

            # THE property: no option on an unsubmitted paper carries a verdict.
            for question in questions:
                assert question["correct_label"] is None
                assert question["is_correct"] is None
                assert all(o["is_correct"] is None for o in question["options"]), (
                    "an unsubmitted paper leaked the answer key"
                )
                # Both languages reach the learner, as everywhere else in the product.
                assert question["text_en"] and question["text_hi"]

            # Answer the first question, leave the rest blank, then change our mind.
            first = questions[0]
            for label in ("A", "B"):
                r = await client.put(
                    f"/api/v1/practice/sessions/{session_id}/answers/{first['id']}",
                    json={"selected_label": label, "seconds_taken": 30},
                    headers=auth,
                )
                assert r.status_code == 204

            r = await client.put(
                f"/api/v1/practice/sessions/{session_id}/answers/999999999",
                json={"selected_label": "A"},
                headers=auth,
            )
            assert r.status_code == 404, "a question not on the paper must be refused"

            r = await client.post(
                f"/api/v1/practice/sessions/{session_id}/submit", headers=auth
            )
            assert r.status_code == 200
            result = r.json()
            assert result["submitted_at"] is not None
            assert result["correct_count"] + result["wrong_count"] <= 1
            assert result["skipped_count"] == practice["question_count"] - 1
            assert result["max_score"] == pytest.approx(
                practice["question_count"] * practice["marks_per_question"]
            )

            # Now, and only now, the key is visible.
            r = await client.get(f"/api/v1/practice/sessions/{session_id}", headers=auth)
            reviewed = r.json()["questions"]
            assert all(q["correct_label"] for q in reviewed)
            assert any(
                o["is_correct"] for q in reviewed for o in q["options"]
            )
            answered = next(q for q in reviewed if q["id"] == first["id"])
            assert answered["selected_label"] == "B"
            assert answered["is_correct"] == (answered["correct_label"] == "B")

            # Re-submitting returns the same sitting rather than rescoring it.
            r = await client.post(
                f"/api/v1/practice/sessions/{session_id}/submit", headers=auth
            )
            assert r.json()["submitted_at"] == result["submitted_at"]

            r = await client.put(
                f"/api/v1/practice/sessions/{session_id}/answers/{first['id']}",
                json={"selected_label": "C"},
                headers=auth,
            )
            assert r.status_code == 409, "a submitted paper must not accept new answers"

            r = await client.get("/api/v1/practice/performance", headers=auth)
            assert r.status_code == 200
            performance = r.json()
            assert performance["submitted_sessions"] == 1
            assert performance["questions_attempted"] >= 1
    finally:
        if email:
            await _cleanup(email)


@pytest.mark.asyncio
async def test_practice_needs_an_account_and_sessions_are_private():
    emails = []
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/practice/performance")
            assert r.status_code == 401, "the learner's own record must require a login"

            owner_email, owner_token = await _register_and_login(client)
            emails.append(owner_email)
            r = await client.post(
                "/api/v1/practice/sessions",
                json={"mode": "full_mock", "count": 5},
                headers={"Authorization": f"Bearer {owner_token}"},
            )
            if r.status_code == 409:
                pytest.skip("no keyed questions ingested")
            session_id = r.json()["id"]

            other_email, other_token = await _register_and_login(client)
            emails.append(other_email)
            r = await client.get(
                f"/api/v1/practice/sessions/{session_id}",
                headers={"Authorization": f"Bearer {other_token}"},
            )
            # 404 rather than 403: another learner's session is not confirmed to exist.
            assert r.status_code == 404
    finally:
        for email in emails:
            await _cleanup(email)


@pytest.mark.asyncio
async def test_a_short_password_is_refused():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": "short"}
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_year_paper_is_one_printed_booklet_not_every_paper_of_that_year():
    """Two papers share a year, so selecting by year alone returns both.

    Before this was scoped, sitting "2026" handed a learner a 180-question paper with two
    questions numbered 1, two numbered 2, and a mark-per-question averaged across a
    2.0-mark paper and a 2.5-mark one. Nothing errored; the sitting was simply not a real
    paper. Paper II also paces differently and qualifies rather than ranks.
    """
    async with async_session_factory() as session:
        gs1 = (
            await session.execute(select(Paper).where(Paper.code == "prelims-gs1"))
        ).scalar_one_or_none()
        gs2 = (
            await session.execute(select(Paper).where(Paper.code == "prelims-gs2"))
        ).scalar_one_or_none()
        if gs1 is None or gs2 is None:
            pytest.skip("both Prelims papers must be seeded")

        shared_years = set(
            (
                await session.execute(
                    select(Question.year)
                    .where(
                        Question.paper_id == gs1.id,
                        Question.status == QuestionStatus.published,
                    )
                    .distinct()
                )
            ).scalars()
        ) & set(
            (
                await session.execute(
                    select(Question.year)
                    .where(
                        Question.paper_id == gs2.id,
                        Question.status == QuestionStatus.published,
                    )
                    .distinct()
                )
            ).scalars()
        )
        if not shared_years:
            pytest.skip("no year has both papers published yet")
        year = max(shared_years)

        for paper in (gs1, gs2):
            ids = await assemble(
                session,
                mode=PracticeMode.year_paper,
                year=year,
                paper_code=paper.code,
            )
            if not ids:
                continue
            paper_ids = set(
                (
                    await session.execute(
                        select(Question.paper_id).where(Question.id.in_(ids)).distinct()
                    )
                ).scalars()
            )
            assert paper_ids == {paper.id}, paper.code

            numbers = [
                n
                for n in (
                    await session.execute(
                        select(Question.question_number).where(Question.id.in_(ids))
                    )
                ).scalars()
            ]
            assert len(numbers) == len(set(numbers)), f"{paper.code} has duplicate numbers"

        # And the two papers pace and qualify differently, which is why the scoping
        # matters beyond the duplicate numbers.
        assert seconds_per_question("prelims-gs2") > seconds_per_question("prelims-gs1")
        assert qualifying_score("prelims-gs1", question_count=100, marks=2.0) is None
        assert qualifying_score("prelims-gs2", question_count=80, marks=2.5) == 66.0
