"""Topic importance ranking — the shared view both Prelims (A1) and Mains use.

Plain SQL aggregate over tagged, published questions; no AI. Two time windows:
all-time and last-N-years (default 5), per the MVP scope doc.

Every ranked topic carries **two** counts, because they answer different questions and
neither is a substitute for the other:

* `question_count` — questions tagged to this topic itself.
* `subtree_count` — questions tagged anywhere in this topic and below.

They diverge violently on branch topics: `gs3.science_technology` holds 1 direct tag and
247 in its subtree, because the tagger nearly always lands on a leaf. Reporting only the
direct count made the ranking wrong; reporting only the subtree count would make a branch
double-count its own children and float the top of the tree to the top of the list. So
`rollup` chooses the sort key and the visibility rule, and both numbers are always
returned.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import Paper, Question, QuestionTopicMap, Topic
from kasauti_api.db.models.taxonomy import Stage
from kasauti_api.domain.intelligence.scope import (
    QuestionScope,
    Rollup,
    newest_year,
    question_ids,
)


@dataclass(frozen=True)
class RankedTopic:
    """One ranked topic.

    `prelims_count` + `mains_count` split whichever count this ranking sorted on
    (`question_count` under `rollup="direct"`, `subtree_count` under `"subtree"`), so the
    pair always sums to the headline number beside it. They exist because the same topic
    tree is now tagged by both stages, and a single number spanning both describes an exam
    nobody sits: `gs1.indian_society` reads 153, which is 64 Prelims questions and 89 Mains
    ones asked in entirely different ways. A stage-scoped ranking simply has a zero in one
    of the two.
    """

    topic_id: int
    path: str
    name_en: str
    name_hi: str
    question_count: int
    latest_year: int
    subtree_count: int
    depth: int
    prelims_count: int = 0
    mains_count: int = 0


def drop_redundant_parents(ranked: list[RankedTopic]) -> list[RankedTopic]:
    """Drop any topic whose subtree corpus is identical to a single descendant's.

    A branch that genuinely aggregates — `gs3.science_technology` at 247 sitting above
    `general_science` at 98 — is worth analysing in its own right. A branch whose count
    exactly equals one descendant's is not: the corpus is the same list of questions, so
    the model would be asked the same thing twice. That is wasteful against an API key
    and outright expensive while every request is answered by hand.
    """
    by_count: dict[int, list[RankedTopic]] = {}
    for topic in ranked:
        by_count.setdefault(topic.subtree_count, []).append(topic)

    return [
        topic
        for topic in ranked
        if not any(
            other.path.startswith(f"{topic.path}.")
            for other in by_count[topic.subtree_count]
        )
    ]


async def topic_importance(
    session: AsyncSession,
    *,
    subject_id: int | None = None,
    stage: Stage | None = None,
    window_years: int | None = None,
    rollup: Rollup = "direct",
    max_depth: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 50,
) -> list[RankedTopic]:
    """Rank topics by how many published questions are tagged to them.

    stage filters by the *question's* paper stage (prelims vs mains), so the
    same topic tree yields separate prelims and mains rankings.
    window_years=None → all-time; N → last N years relative to the newest
    question year *in scope*.

    rollup chooses which count orders the list and which topics appear at all:
    "direct" keeps the historical behaviour (a topic shows up only if questions are
    tagged to it), "subtree" surfaces branch topics whose questions all sit on their
    leaves. Pair "subtree" with max_depth to get a non-overlapping list — without it a
    parent and its children all appear, with the parent's count including the children's.
    """
    scope = QuestionScope(
        stage=stage,
        subject_id=subject_id,
        year_from=year_from,
        year_to=year_to,
    )
    if window_years is not None:
        # Anchored inside the scope: with Prelims 2026 loaded, a mains 5-year window
        # anchored on the global maximum would silently return nothing.
        anchor = (await session.execute(newest_year(scope))).scalar()
        if anchor is None:
            return []
        floor = anchor - window_years + 1
        scope = QuestionScope(
            stage=scope.stage,
            subject_id=scope.subject_id,
            year_from=max(floor, scope.year_from) if scope.year_from else floor,
            year_to=scope.year_to,
        )

    in_scope = Question.id.in_(question_ids(scope))

    # Self-join the tree by ltree containment: every topic is joined to itself and to
    # its descendants, so one pass yields both counts. FILTER isolates the direct half.
    descendant = Topic.__table__.alias("descendant")
    direct_count = func.count(func.distinct(Question.id)).filter(
        descendant.c.id == Topic.id
    )
    subtree_count = func.count(func.distinct(Question.id))
    latest = func.max(Question.year)

    # The same two counts split by stage. Prelims Paper 1 tags onto the gs1-gs4 trees via
    # `paper_subject_map`, so once Mains was ingested every one of those topics carried
    # both stages and an unstaged ranking silently summed two exams onto one row. Splitting
    # in this pass rather than merging two `stage=`-scoped calls in the caller is not a
    # preference: `limit` applies per call, so a topic inside Mains' top N but outside
    # Prelims' would come back with an absent Prelims count that is not actually zero.
    def _by_stage(base, stage_value: Stage):
        return func.count(func.distinct(Question.id)).filter(
            *base, Paper.stage == stage_value
        )

    direct_only = (descendant.c.id == Topic.id,)
    prelims_direct = _by_stage(direct_only, Stage.prelims)
    mains_direct = _by_stage(direct_only, Stage.mains)
    prelims_subtree = _by_stage((), Stage.prelims)
    mains_subtree = _by_stage((), Stage.mains)

    stmt = (
        select(
            Topic.id,
            Topic.path,
            Topic.name_en,
            Topic.name_hi,
            Topic.depth,
            direct_count.label("direct_count"),
            subtree_count.label("subtree_count"),
            latest.label("latest_year"),
            prelims_direct.label("prelims_direct"),
            mains_direct.label("mains_direct"),
            prelims_subtree.label("prelims_subtree"),
            mains_subtree.label("mains_subtree"),
        )
        .join(descendant, descendant.c.path.descendant_of(Topic.path))
        .join(QuestionTopicMap, QuestionTopicMap.topic_id == descendant.c.id)
        .join(Question, Question.id == QuestionTopicMap.question_id)
        .join(Paper, Paper.id == Question.paper_id)
        .where(in_scope)
        .group_by(Topic.id)
        .limit(limit)
    )
    if subject_id is not None:
        stmt = stmt.where(Topic.subject_id == subject_id)
    if max_depth is not None:
        stmt = stmt.where(Topic.depth <= max_depth)

    order_key = subtree_count if rollup == "subtree" else direct_count
    # A topic with no questions under the chosen count is not "ranked 0" — it is absent,
    # which is what the direct-only version did and what callers already expect.
    stmt = stmt.having(order_key > 0).order_by(order_key.desc(), latest.desc())

    rows = (await session.execute(stmt)).all()
    # The stage split reports on whichever basis this ranking sorted on, so the pair always
    # adds up to the count sitting next to it rather than to the other one.
    subtree = rollup == "subtree"
    return [
        RankedTopic(
            topic_id=r[0],
            path=str(r[1]),
            name_en=r[2],
            name_hi=r[3],
            depth=r[4],
            question_count=r[5],
            subtree_count=r[6],
            latest_year=r[7],
            prelims_count=r[10] if subtree else r[8],
            mains_count=r[11] if subtree else r[9],
        )
        for r in rows
    ]
