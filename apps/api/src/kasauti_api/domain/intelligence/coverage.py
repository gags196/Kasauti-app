"""How thoroughly UPSC has worked over a topic, and where inside it.

Plain SQL, no LLM. Two views of one thing:

* `year_series` — how many questions per year, which is what a trend line is drawn from.
* `subtree_coverage` — the same counts broken out per child branch, so a learner can see
  which parts of a topic carry the weight and which have barely been touched.

**The word "exhausted" is deliberately absent.** UPSC repeats itself freely; nine
questions in fourteen years does not close a topic, and a UI that says "exhausted" is
making a prediction while looking like it is reporting a measurement. `probe_status` says
only how heavily something has been asked, and its thresholds are conventions — named
here, documented as conventions, and not derived from anything.

Note also that taxonomy-leaf coverage is nearly saturated for Prelims: 67 of the 72 leaves
under gs1/gs2/gs3 already carry questions. A "syllabus areas never asked" view built on
the tree would tell a learner almost nothing. The finer-grained answer needs the concepts
probed *inside* a leaf, which is what the classification pass adds.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import Question, QuestionTopicMap, Topic
from kasauti_api.db.models.taxonomy import Stage
from kasauti_api.domain.intelligence.scope import (
    QuestionScope,
    Rollup,
    question_ids,
    topic_match,
)

UNPROBED = "unprobed"
LIGHTLY_PROBED = "lightly_probed"
PROBED = "probed"
HEAVILY_PROBED = "heavily_probed"

# Conventions, not measurements. Calibrated to a fourteen-year, 1,400-question corpus in
# which the average tagged leaf carries about twenty questions. Change them freely — but
# change them here, so every surface that shows a badge agrees.
PROBE_THRESHOLDS = (0, 3, 15)


@dataclass(frozen=True)
class YearCount:
    year: int
    count: int


@dataclass(frozen=True)
class BranchCoverage:
    topic_id: int
    path: str
    name_en: str
    name_hi: str
    depth: int
    direct_count: int
    subtree_count: int
    first_year: int | None
    latest_year: int | None
    probe_status: str


def probe_status(subtree_count: int) -> str:
    """How heavily a topic has been asked. Says nothing about what comes next."""
    unprobed, lightly, probed = PROBE_THRESHOLDS
    if subtree_count <= unprobed:
        return UNPROBED
    if subtree_count <= lightly:
        return LIGHTLY_PROBED
    if subtree_count <= probed:
        return PROBED
    return HEAVILY_PROBED


async def year_series(
    session: AsyncSession,
    topic: Topic,
    *,
    rollup: Rollup = "subtree",
    stage: Stage | None = None,
    fill_gaps: bool = True,
) -> list[YearCount]:
    """Questions per year for a topic.

    `fill_gaps` emits explicit zeros for years the corpus covers but the topic misses. A
    sparkline that silently skips 2018 reads as continuity where there was a gap.
    """
    scope = QuestionScope(topic_path=str(topic.path), rollup=rollup, stage=stage)
    rows = (
        await session.execute(
            select(Question.year, func.count(Question.id))
            .where(Question.id.in_(question_ids(scope)))
            .group_by(Question.year)
            .order_by(Question.year)
        )
    ).all()
    counts = {year: n for year, n in rows}
    if not counts:
        return []
    if not fill_gaps:
        return [YearCount(year, n) for year, n in sorted(counts.items())]

    corpus_years = (
        await session.execute(
            select(func.min(Question.year), func.max(Question.year)).where(
                Question.id.in_(question_ids(QuestionScope(stage=stage)))
            )
        )
    ).one()
    first, last = corpus_years
    if first is None:
        return [YearCount(year, n) for year, n in sorted(counts.items())]
    return [YearCount(year, counts.get(year, 0)) for year in range(first, last + 1)]


async def subtree_coverage(
    session: AsyncSession,
    topic: Topic,
    *,
    stage: Stage | None = None,
    include_self: bool = False,
) -> list[BranchCoverage]:
    """Every descendant of this topic with its own counts, heaviest first.

    Descendants with **zero** questions are included on purpose. Hiding them would make
    the topic look uniformly covered and quietly delete the only genuinely actionable
    part of the view — the branches nothing has been asked from yet.
    """
    scope = QuestionScope(stage=stage)
    in_scope = Question.id.in_(question_ids(scope))

    descendant = Topic.__table__.alias("descendant")
    direct = func.count(func.distinct(Question.id)).filter(descendant.c.id == Topic.id)
    subtree = func.count(func.distinct(Question.id))

    stmt = (
        select(
            Topic.id,
            Topic.path,
            Topic.name_en,
            Topic.name_hi,
            Topic.depth,
            direct.label("direct_count"),
            subtree.label("subtree_count"),
            func.min(Question.year).label("first_year"),
            func.max(Question.year).label("latest_year"),
        )
        .select_from(Topic)
        # Outer joins throughout: a topic with no questions must still produce a row.
        .join(descendant, descendant.c.path.descendant_of(Topic.path), isouter=True)
        .join(
            QuestionTopicMap,
            QuestionTopicMap.topic_id == descendant.c.id,
            isouter=True,
        )
        .join(
            Question,
            (Question.id == QuestionTopicMap.question_id) & in_scope,
            isouter=True,
        )
        .where(topic_match(str(topic.path), "subtree"))
        .group_by(Topic.id)
        .order_by(subtree.desc(), Topic.path)
    )
    if not include_self:
        stmt = stmt.where(Topic.id != topic.id)

    return [
        BranchCoverage(
            topic_id=r[0], path=str(r[1]), name_en=r[2], name_hi=r[3], depth=r[4],
            direct_count=r[5], subtree_count=r[6], first_year=r[7], latest_year=r[8],
            probe_status=probe_status(r[6]),
        )
        for r in (await session.execute(stmt)).all()
    ]


async def gap_years(
    session: AsyncSession, topic: Topic, *, stage: Stage | None = None
) -> list[int]:
    """Years in the corpus window where this topic was not asked at all."""
    return [yc.year for yc in await year_series(session, topic, stage=stage) if yc.count == 0]
