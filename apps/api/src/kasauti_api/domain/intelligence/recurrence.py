"""Which questions rhyme with an earlier question on the same topic.

Runs entirely on the `question_embeddings` rows the ingestion pipeline already writes —
no model calls, no new storage. Two questions sharing a topic whose vectors sit close
together are, in practice, the same question archetype asked twice:

    0.906  2015 "Which National Park has a climate varying from tropical to arctic?"
           2019 "Which National Park lies completely in the temperate alpine zone?"
    0.816  2017 "if a species of tortoise is declared protected under Schedule I of the
                 Wildlife (Protection) Act, what does it imply?"
           2020 "if a plant species is placed under Schedule VI …, what is the implication?"

**This is selective, not universal, and the per-topic rate is the product.** Corpus-wide,
288 of 1,400 questions have a same-topic sibling at 0.75 or above and 123 at 0.80 — but
`gs2.polity.parliament` and `gs1.geography.indian_geography` recur at 44% while
biodiversity manages 26%. A single headline number would flatten exactly the variation a
learner would act on, so nothing here returns one.

The threshold is a convention. 0.75 is set where the pairs stop reading as the same
archetype on inspection; it is not derived, and it is exposed so a caller can disagree.
"""

from dataclasses import dataclass

from sqlalchemy import Float, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from kasauti_api.db.models import Question, QuestionEmbedding, QuestionTopicMap, Topic
from kasauti_api.db.models.taxonomy import Stage
from kasauti_api.domain.intelligence.scope import (
    QuestionScope,
    Rollup,
    question_ids,
    topic_match,
)

# Cosine similarity above which two same-topic questions read as one archetype.
DEFAULT_THRESHOLD = 0.75
# Vectors are only comparable inside one model's space, so a corpus holding both real
# Voyage vectors and dev hashing-provider vectors must never mix them in one comparison.
DEFAULT_LANG = "en"


@dataclass(frozen=True)
class RepeatedPair:
    similarity: float
    earlier_id: int
    earlier_year: int
    earlier_text: str | None
    later_id: int
    later_year: int
    later_text: str | None
    years_apart: int


@dataclass(frozen=True)
class TopicRecurrence:
    topic_id: int
    path: str
    questions: int
    recurring: int
    threshold: float

    @property
    def rate(self) -> float:
        return self.recurring / self.questions if self.questions else 0.0


def _scoped_vectors(
    scope: QuestionScope, *, lang: str, embedding_model: str | None
):
    """CTE of (topic_id, question_id, embedding) for every in-scope tagged question.

    Materialising this once matters: expressing the same thing as two `IN (subquery)`
    filters inside a self-join made Postgres re-evaluate the scope per candidate pair,
    and the corpus-wide query did not finish inside two minutes. As a CTE it is a
    sub-second scan.
    """
    stmt = (
        select(
            QuestionTopicMap.topic_id.label("topic_id"),
            QuestionTopicMap.question_id.label("question_id"),
            QuestionEmbedding.embedding.label("embedding"),
        )
        .join(
            QuestionEmbedding,
            QuestionEmbedding.question_id == QuestionTopicMap.question_id,
        )
        .where(
            QuestionEmbedding.lang == lang,
            QuestionTopicMap.question_id.in_(question_ids(scope)),
        )
    )
    if embedding_model:
        stmt = stmt.where(QuestionEmbedding.embedding_model == embedding_model)
    return stmt.cte("scoped_vectors")


async def repeated_pairs(
    session: AsyncSession,
    topic: Topic,
    *,
    rollup: Rollup = "subtree",
    stage: Stage | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    lang: str = DEFAULT_LANG,
    embedding_model: str | None = None,
    min_years_apart: int = 1,
    limit: int = 20,
) -> list[RepeatedPair]:
    """Question pairs inside one topic that sit above the similarity threshold.

    Ordered by similarity, most alike first. `a.id < b.id` keeps each pair once.

    `min_years_apart=1` by default because the claim this supports is "UPSC came back to
    this angle". Two near-identical questions in the *same* paper — 2024 asked about a
    bill pending in the Lok Sabha twice — are a curiosity about that paper, not evidence
    the archetype recurs. Pass 0 to see them.
    """
    scope = QuestionScope(topic_path=str(topic.path), rollup=rollup, stage=stage)
    vectors = _scoped_vectors(scope, lang=lang, embedding_model=embedding_model)
    a, b = vectors.alias("a"), vectors.alias("b")
    q_left, q_right = aliased(Question), aliased(Question)
    similarity = 1 - a.c.embedding.cosine_distance(b.c.embedding)

    stmt = (
        select(
            cast(similarity, Float).label("similarity"),
            q_left.id, q_left.year, q_left.question_text_en,
            q_right.id, q_right.year, q_right.question_text_en,
        )
        .select_from(a)
        # a.question_id < b.question_id keeps each pair once; same topic keeps the
        # comparison meaningful, since two questions only "rhyme" within a subject.
        .join(
            b,
            and_(b.c.topic_id == a.c.topic_id, a.c.question_id < b.c.question_id),
        )
        .join(q_left, q_left.id == a.c.question_id)
        .join(q_right, q_right.id == b.c.question_id)
        .where(
            similarity >= threshold,
            func.abs(q_right.year - q_left.year) >= min_years_apart,
        )
        .order_by(similarity.desc())
        .limit(limit)
    )

    pairs = []
    for sim, lid, lyear, ltext, rid, ryear, rtext in (await session.execute(stmt)).all():
        earlier = (lid, lyear, ltext) if lyear <= ryear else (rid, ryear, rtext)
        later = (rid, ryear, rtext) if lyear <= ryear else (lid, lyear, ltext)
        pairs.append(
            RepeatedPair(
                similarity=float(sim),
                earlier_id=earlier[0], earlier_year=earlier[1], earlier_text=earlier[2],
                later_id=later[0], later_year=later[1], later_text=later[2],
                years_apart=abs(ryear - lyear),
            )
        )
    return pairs


async def topic_recurrence(
    session: AsyncSession,
    *,
    stage: Stage | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    lang: str = DEFAULT_LANG,
    embedding_model: str | None = None,
    min_questions: int = 10,
) -> list[TopicRecurrence]:
    """Per-topic share of questions that rhyme with another in the same topic.

    `min_questions` exists because a rate over five questions is a coin flip wearing a
    percentage sign. Topics below it are omitted rather than shown with a noisy number.
    """
    vectors = _scoped_vectors(
        QuestionScope(stage=stage), lang=lang, embedding_model=embedding_model
    )
    a, b = vectors.alias("a"), vectors.alias("b")
    similarity = 1 - a.c.embedding.cosine_distance(b.c.embedding)

    # Per (topic, question), whether any same-topic sibling clears the threshold.
    has_sibling = (
        select(
            a.c.topic_id.label("topic_id"),
            a.c.question_id.label("question_id"),
            func.bool_or(similarity >= threshold).label("recurs"),
        )
        .select_from(a)
        .join(
            b,
            and_(b.c.topic_id == a.c.topic_id, b.c.question_id != a.c.question_id),
        )
        .group_by(a.c.topic_id, a.c.question_id)
        .subquery()
    )

    total = func.count()
    recurring = func.count().filter(has_sibling.c.recurs)
    stmt = (
        select(Topic.id, Topic.path, total, recurring)
        .join(has_sibling, has_sibling.c.topic_id == Topic.id)
        .group_by(Topic.id)
        .having(total >= min_questions)
        .order_by((cast(recurring, Float) / total).desc(), total.desc())
    )
    return [
        TopicRecurrence(
            topic_id=r[0], path=str(r[1]), questions=r[2], recurring=r[3],
            threshold=threshold,
        )
        for r in (await session.execute(stmt)).all()
    ]


async def corpus_recurrence(
    session: AsyncSession,
    *,
    stage: Stage | None = None,
    thresholds: tuple[float, ...] = (0.90, 0.85, 0.80, 0.75),
    lang: str = DEFAULT_LANG,
    embedding_model: str | None = None,
) -> dict[float, int]:
    """How many questions have a same-topic sibling at each threshold.

    Reported as a curve rather than one number, because "questions repeat" is only a
    meaningful claim alongside how alike "repeat" was taken to mean.
    """
    vectors = _scoped_vectors(
        QuestionScope(stage=stage), lang=lang, embedding_model=embedding_model
    )
    a, b = vectors.alias("a"), vectors.alias("b")
    similarity = 1 - a.c.embedding.cosine_distance(b.c.embedding)

    best = (
        select(
            a.c.question_id.label("question_id"),
            func.max(similarity).label("best"),
        )
        .select_from(a)
        .join(
            b,
            and_(b.c.topic_id == a.c.topic_id, b.c.question_id != a.c.question_id),
        )
        .group_by(a.c.question_id)
        .subquery()
    )

    columns = [
        func.count().filter(best.c.best >= t).label(f"t{int(t * 100)}") for t in thresholds
    ]
    row = (await session.execute(select(*columns).select_from(best))).one()
    return dict(zip(thresholds, row, strict=True))


async def topic_by_path(session: AsyncSession, path: str) -> Topic | None:
    return (
        await session.execute(select(Topic).where(topic_match(path, "direct")))
    ).scalar_one_or_none()
