"""API-level tests for /api/v1/pyq against local Postgres (no LLM calls;
search is covered separately since it needs an embedding provider)."""

import pytest
from httpx import ASGITransport, AsyncClient
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import (
    Exam,
    Paper,
    Question,
    QuestionOption,
    QuestionTopicMap,
    Topic,
    TopicAnalysis,
    TopicNote,
)
from kasauti_api.db.models.intelligence import AnalysisScope, TopicNoteStatus
from kasauti_api.db.models.questions import QuestionLanguage, QuestionStatus, TaggedBy
from kasauti_api.main import app
from sqlalchemy import delete, func, select
from sqlalchemy_utils import Ltree

TOPIC_PATH = "gs2.constitution.federalism"


@pytest.mark.asyncio
async def test_pyq_endpoints():
    async with async_session_factory() as session:
        exam = (
            await session.execute(select(Exam).where(Exam.code == "upsc-cse"))
        ).scalar_one_or_none()
        if exam is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
        prelims = (
            await session.execute(
                select(Paper).where(Paper.exam_id == exam.id, Paper.code == "prelims-gs1")
            )
        ).scalar_one()
        topic = (
            await session.execute(select(Topic).where(Topic.path == Ltree(TOPIC_PATH)))
        ).scalar_one()

        # The local DB is shared with demo fixtures and real ingested data, so
        # record what already exists and only clean up rows this test adds.
        pre_analyses = set(
            (
                await session.execute(
                    select(TopicAnalysis.id).where(TopicAnalysis.topic_id == topic.id)
                )
            ).scalars()
        )
        pre_notes = set(
            (
                await session.execute(
                    select(TopicNote.id).where(TopicNote.topic_id == topic.id)
                )
            ).scalars()
        )

        q = Question(
            exam_id=exam.id, paper_id=prelims.id, year=2022, question_number="7",
            marks=2, language=QuestionLanguage.bilingual,
            question_text_en="Which of the following relates to fiscal federalism?",
            question_text_hi="निम्नलिखित में से कौन राजकोषीय संघवाद से संबंधित है?",
            status=QuestionStatus.published,
        )
        session.add(q)
        await session.flush()
        session.add_all([
            QuestionOption(question_id=q.id, option_label="A", option_text_en="GST Council"),
            QuestionOption(question_id=q.id, option_label="B", option_text_en="Article 32"),
        ])
        session.add(QuestionTopicMap(question_id=q.id, topic_id=topic.id,
                                     confidence=1.0, tagged_by=TaggedBy.human))
        session.add(TopicAnalysis(
            topic_id=topic.id, scope=AnalysisScope.combined, model_name="test",
            prompt_ref="prompts/intelligence/topic_analysis_v1.md", question_count=1,
            pattern_summary_en="s", pattern_summary_hi="स",
            predicted_angles=[{"angle_en": "x", "angle_hi": "य", "rationale_en": "r"}],
        ))
        # /note serves the highest version, so this must outrank any note the
        # topic already carries.
        next_version = (
            await session.execute(
                select(func.coalesce(func.max(TopicNote.version), 0) + 1).where(
                    TopicNote.topic_id == topic.id
                )
            )
        ).scalar_one()
        session.add(TopicNote(
            topic_id=topic.id, version=next_version, model_name="test",
            prompt_ref="prompts/intelligence/one_pager_v1.md", question_count=1,
            content_en={"title": "Federalism"}, content_hi={"title": "संघवाद"},
            status=TopicNoteStatus.published,
        ))
        await session.commit()
        q_id, topic_id = q.id, topic.id

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/v1/pyq/topics")
            assert r.status_code == 200
            assert any(t["path"] == TOPIC_PATH for t in r.json())

            r = await client.get("/api/v1/pyq/rankings", params={"stage": "prelims"})
            assert r.status_code == 200
            entry = next(x for x in r.json() if x["topic_id"] == topic_id)
            assert entry["question_count"] >= 1

            r = await client.get(f"/api/v1/pyq/topics/{topic_id}/analysis")
            assert r.status_code == 200
            assert r.json()["predicted_angles"][0]["angle_hi"] == "य"

            r = await client.get(f"/api/v1/pyq/topics/{topic_id}/note")
            assert r.status_code == 200
            assert r.json()["content_hi"]["title"] == "संघवाद"

            r = await client.get(f"/api/v1/pyq/questions/{q_id}")
            assert r.status_code == 200
            body = r.json()
            assert body["topic_paths"] == [TOPIC_PATH]
            assert [o["label"] for o in body["options"]] == ["A", "B"]

            r = await client.get("/api/v1/pyq/questions/999999999")
            assert r.status_code == 404
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(TopicAnalysis).where(
                    TopicAnalysis.topic_id == topic_id,
                    TopicAnalysis.id.notin_(pre_analyses),
                )
            )
            await session.execute(
                delete(TopicNote).where(
                    TopicNote.topic_id == topic_id, TopicNote.id.notin_(pre_notes)
                )
            )
            await session.execute(
                delete(QuestionOption).where(QuestionOption.question_id == q_id)
            )
            await session.execute(
                delete(QuestionTopicMap).where(QuestionTopicMap.question_id == q_id)
            )
            await session.execute(delete(Question).where(Question.id == q_id))
            await session.commit()


@pytest.mark.asyncio
async def test_analysis_endpoint_ignores_backtests():
    """A backtest is written *after* the live analysis and is deliberately blind to
    recent years. Ordering by generated_at alone would serve it to learners as the
    current view."""
    async with async_session_factory() as session:
        topic = (
            await session.execute(select(Topic).where(Topic.path == Ltree(TOPIC_PATH)))
        ).scalar_one_or_none()
        if topic is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
        topic_id = topic.id
        pre_analyses = set(
            (
                await session.execute(
                    select(TopicAnalysis.id).where(TopicAnalysis.topic_id == topic_id)
                )
            ).scalars()
        )

        def _analysis(marker: str, *, backtest: bool, **kw) -> TopicAnalysis:
            return TopicAnalysis(
                topic_id=topic_id, scope=AnalysisScope.combined, model_name="test",
                prompt_ref="prompts/intelligence/topic_analysis_v1.md", question_count=1,
                pattern_summary_en=marker, pattern_summary_hi=marker,
                predicted_angles=[], is_backtest=backtest, **kw,
            )

        session.add(_analysis("live", backtest=False))
        await session.commit()
        # Committed second, so it is unambiguously the newest row for this topic.
        session.add(_analysis("backtest", backtest=True, corpus_year_max=2023))
        await session.commit()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get(f"/api/v1/pyq/topics/{topic_id}/analysis")
            assert r.status_code == 200
            assert r.json()["pattern_summary_en"] == "live"
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(TopicAnalysis).where(
                    TopicAnalysis.topic_id == topic_id,
                    TopicAnalysis.id.notin_(pre_analyses),
                )
            )
            await session.commit()
