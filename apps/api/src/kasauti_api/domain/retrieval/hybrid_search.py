"""The one retrieval function (plan §3): SQL filters → pgvector cosine →
heuristic rerank. Two consumers share it — PYQ intelligence queries and
evaluation rubric-grounding citation lookups — so relevance improvements land
in both at once.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_utils import Ltree

from kasauti_api.db.models import Question, QuestionEmbedding, QuestionTopicMap, Topic
from kasauti_api.db.models.questions import QuestionStatus


@dataclass(frozen=True)
class SearchFilters:
    exam_id: int | None = None
    paper_id: int | None = None
    topic_path: str | None = None  # ltree prefix, e.g. "maths1.calculus"
    year_from: int | None = None
    year_to: int | None = None
    marks: float | None = None
    # Vectors are only comparable within one model's space — set this to the
    # querying provider's model so a model swap can't silently mix spaces.
    embedding_model: str | None = None


@dataclass
class SearchHit:
    question: Question
    distance: float
    score: float = field(default=0.0)


# Heuristic rerank weights: similarity dominates; recency and marks-match nudge.
W_SIMILARITY = 1.0
W_RECENCY = 0.15
W_MARKS = 0.05
CANDIDATE_MULTIPLIER = 3


def _heuristic_score(hit: SearchHit, filters: SearchFilters, current_year: int) -> float:
    similarity = 1.0 - hit.distance
    recency = max(0.0, 1.0 - (current_year - hit.question.year) / 40.0)
    marks_match = 0.0
    if filters.marks is not None and hit.question.marks is not None:
        marks_match = 1.0 if float(hit.question.marks) == float(filters.marks) else 0.0
    return W_SIMILARITY * similarity + W_RECENCY * recency + W_MARKS * marks_match


async def search_questions(
    session: AsyncSession,
    *,
    query_embedding: list[float],
    filters: SearchFilters | None = None,
    k: int = 20,
    rerank: bool = True,
) -> list[SearchHit]:
    """Semantic search over published questions.

    The query embedding is compared against every language variant of each
    question (shared multilingual space), keeping the best match per question.
    """
    filters = filters or SearchFilters()

    dist = func.min(
        QuestionEmbedding.embedding.cosine_distance(query_embedding)
    ).label("dist")
    stmt = (
        select(Question, dist)
        .join(QuestionEmbedding, QuestionEmbedding.question_id == Question.id)
        .where(Question.status == QuestionStatus.published)
        .group_by(Question.id)
        .order_by(dist)
        .limit(k * CANDIDATE_MULTIPLIER if rerank else k)
    )

    if filters.embedding_model is not None:
        stmt = stmt.where(QuestionEmbedding.embedding_model == filters.embedding_model)
    if filters.exam_id is not None:
        stmt = stmt.where(Question.exam_id == filters.exam_id)
    if filters.paper_id is not None:
        stmt = stmt.where(Question.paper_id == filters.paper_id)
    if filters.year_from is not None:
        stmt = stmt.where(Question.year >= filters.year_from)
    if filters.year_to is not None:
        stmt = stmt.where(Question.year <= filters.year_to)
    if filters.topic_path is not None:
        stmt = stmt.where(
            exists(
                select(QuestionTopicMap.question_id)
                .join(Topic, Topic.id == QuestionTopicMap.topic_id)
                .where(
                    QuestionTopicMap.question_id == Question.id,
                    Topic.path.descendant_of(Ltree(filters.topic_path)),
                )
            )
        )

    rows = (await session.execute(stmt)).all()
    hits = [SearchHit(question=q, distance=float(d)) for q, d in rows]

    if rerank:
        year = datetime.now().year
        for hit in hits:
            hit.score = _heuristic_score(hit, filters, year)
        hits.sort(key=lambda h: h.score, reverse=True)
        hits = hits[:k]
    else:
        for hit in hits:
            hit.score = 1.0 - hit.distance

    return hits
