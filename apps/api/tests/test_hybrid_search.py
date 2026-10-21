"""Embedding task + hybrid search against local Postgres with a fake embedder.
Requires the taxonomy seed."""

import pytest
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import (
    Exam,
    LlmUsageEvent,
    Paper,
    Question,
    QuestionEmbedding,
    QuestionTopicMap,
    Topic,
)
from kasauti_api.db.models.questions import QuestionLanguage, QuestionStatus, TaggedBy
from kasauti_api.domain.llm.provider import LlmUsage
from kasauti_api.domain.retrieval.hybrid_search import SearchFilters, search_questions
from kasauti_api.workers.embedding_tasks import embed_question
from sqlalchemy import delete, select
from sqlalchemy_utils import Ltree

DIM = 1024


def unit_vec(hot: int) -> list[float]:
    v = [0.0] * DIM
    v[hot] = 1.0
    return v


class FakeEmbedder:
    """Maps texts to fixed unit vectors by keyword, so similarity is controllable."""

    model_name = "fake-embed"

    async def embed(self, texts, *, input_type):
        vectors = []
        for text in texts:
            vectors.append(unit_vec(0) if "eigen" in text.lower() else unit_vec(1))
        usage = LlmUsage(provider="fake", model="fake-embed",
                         input_tokens=10 * len(texts), output_tokens=0)
        return vectors, usage


async def _make_question(session, paper, topic_path: str, text_en: str, text_hi: str | None):
    q = Question(
        exam_id=paper.exam_id,
        paper_id=paper.id,
        year=2020,
        question_number="1",
        marks=10,
        language=QuestionLanguage.bilingual if text_hi else QuestionLanguage.en,
        question_text_en=text_en,
        question_text_hi=text_hi,
        status=QuestionStatus.published,
    )
    session.add(q)
    await session.flush()
    topic = (
        await session.execute(select(Topic).where(Topic.path == Ltree(topic_path)))
    ).scalar_one()
    session.add(
        QuestionTopicMap(question_id=q.id, topic_id=topic.id, confidence=1.0,
                         tagged_by=TaggedBy.human)
    )
    return q


@pytest.mark.asyncio
async def test_embed_and_search(monkeypatch):
    async with async_session_factory() as session:
        exam = (
            await session.execute(select(Exam).where(Exam.code == "upsc-cse"))
        ).scalar_one_or_none()
        if exam is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
        paper = (
            await session.execute(
                select(Paper).where(Paper.exam_id == exam.id, Paper.code == "mains-maths-1")
            )
        ).scalar_one()
        q_eigen = await _make_question(
            session,
            paper,
            "maths1.linear_algebra.eigenvalues_eigenvectors",
            "Find the eigenvalues of the matrix.",
            "आव्यूह के आइगेनमान ज्ञात कीजिए।",
        )
        q_curve = await _make_question(
            session,
            paper,
            "maths1.calculus.maxima_minima",
            "Trace the curve and find its asymptotes.",
            None,
        )
        await session.commit()
        eigen_id, curve_id = q_eigen.id, q_curve.id

    try:
        fake = FakeEmbedder()
        await embed_question({"embedding_provider": fake}, eigen_id)
        await embed_question({"embedding_provider": fake}, curve_id)

        async with async_session_factory() as session:
            emb_count = len(
                (
                    await session.execute(
                        select(QuestionEmbedding).where(
                            QuestionEmbedding.question_id.in_([eigen_id, curve_id])
                        )
                    )
                ).scalars().all()
            )
            assert emb_count == 3  # bilingual question gets en+hi rows, English-only gets one

            # A query near the "eigen" vector should rank the eigen question first.
            hits = await search_questions(
                session, query_embedding=unit_vec(0), k=5,
                # Scoping to this test's embedding model isolates it from demo
                # fixtures and real ingested questions sharing the local DB.
                filters=SearchFilters(paper_id=paper.id, embedding_model=fake.model_name),
            )
            assert hits and hits[0].question.id == eigen_id

            # ltree topic filter: scoping to calculus must exclude the eigen question.
            hits = await search_questions(
                session,
                query_embedding=unit_vec(0),
                filters=SearchFilters(
                    topic_path="maths1.calculus", embedding_model=fake.model_name
                ),
                k=5,
            )
            assert [h.question.id for h in hits] == [curve_id]
    finally:
        async with async_session_factory() as session:
            ids = [eigen_id, curve_id]
            await session.execute(
                delete(QuestionEmbedding).where(QuestionEmbedding.question_id.in_(ids))
            )
            await session.execute(
                delete(QuestionTopicMap).where(QuestionTopicMap.question_id.in_(ids))
            )
            await session.execute(
                delete(LlmUsageEvent).where(
                    LlmUsageEvent.related_entity_type == "question",
                    LlmUsageEvent.related_entity_id.in_([str(i) for i in ids]),
                )
            )
            await session.execute(delete(Question).where(Question.id.in_(ids)))
            await session.commit()
