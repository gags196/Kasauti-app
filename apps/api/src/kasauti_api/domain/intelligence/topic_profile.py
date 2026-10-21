"""One assembled picture of a topic, and what comparable topics suggest about it.

This is the "depth" feature, in both senses the founder meant:

* **Structural** — how far down the tree a topic's questions land, which of its branches
  carry the weight, which have barely been touched, which years it skipped.
* **Cognitive** — the mix of question formats and depths it is examined with, and how
  often its questions rhyme with an earlier one.

And then the transfer: **peers**. A topic that has been drilled hard tells you what being
drilled hard looks like, and a comparable topic that has not yet been sets up an
expectation. The projection here is entirely deterministic — the peers' *measured* mix,
not a model's opinion — so it ships without a single LLM call and carries its evidence
with it.

Two honesty rules are enforced in the types rather than left to the caller:

* `TransferPrediction.confidence_note` is always populated. A projection built from three
  sibling topics is not the same object as one built from thirty, and the difference has
  to travel with the number.
* `DepthProfile.profiled_count` is separate from `question_count`. The cognitive half
  depends on the classification pass, which is backfilled newest-first; until it
  finishes, the mixes describe a subset and must say which.
"""

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import Question, QuestionProfile, QuestionTopicMap, Topic
from kasauti_api.db.models.taxonomy import Stage
from kasauti_api.domain.intelligence.coverage import (
    BranchCoverage,
    YearCount,
    probe_status,
    subtree_coverage,
    year_series,
)
from kasauti_api.domain.intelligence.recurrence import (
    DEFAULT_THRESHOLD,
    RepeatedPair,
    repeated_pairs,
)
from kasauti_api.domain.intelligence.scope import QuestionScope, Rollup, question_ids

# Below this a peer contributes noise rather than a comparison.
MIN_PEER_QUESTIONS = 8
DEFAULT_PEER_LIMIT = 5


@dataclass(frozen=True)
class PeerTopic:
    topic_id: int
    path: str
    name_en: str
    name_hi: str
    subtree_count: int
    profiled_count: int
    basis: str  # "sibling" | "same_depth_in_subject"


@dataclass(frozen=True)
class DepthProfile:
    topic_id: int
    path: str
    name_en: str
    name_hi: str
    question_count: int
    profiled_count: int
    probe_status: str
    first_year: int | None
    latest_year: int | None
    gap_years: list[int]
    format_mix: dict[str, int] = field(default_factory=dict)
    depth_mix: dict[str, int] = field(default_factory=dict)
    archetype_mix: dict[str, int] = field(default_factory=dict)
    mean_statement_count: float | None = None
    recurrence_rate: float | None = None
    year_counts: list[YearCount] = field(default_factory=list)
    branches: list[BranchCoverage] = field(default_factory=list)
    repeats: list[RepeatedPair] = field(default_factory=list)

    @property
    def classified_share(self) -> float:
        return self.profiled_count / self.question_count if self.question_count else 0.0


@dataclass(frozen=True)
class TransferPrediction:
    topic_id: int
    peers: list[PeerTopic]
    peer_question_count: int
    expected_format_mix: dict[str, float]
    expected_depth_mix: dict[str, float]
    expected_questions_per_year: float | None
    untouched_branches: list[BranchCoverage]
    confidence_note: str


async def _mix(
    session: AsyncSession, scope: QuestionScope, column
) -> tuple[dict[str, int], int]:
    """Counts per enum value for one profile column, plus how many rows carried a value."""
    rows = (
        await session.execute(
            select(cast(column, String), func.count(Question.id))
            .join(QuestionProfile, QuestionProfile.question_id == Question.id)
            .where(Question.id.in_(question_ids(scope)), column.is_not(None))
            .group_by(cast(column, String))
            .order_by(func.count(Question.id).desc())
        )
    ).all()
    counts = {name: n for name, n in rows}
    return counts, sum(counts.values())


async def build_depth_profile(
    session: AsyncSession,
    topic: Topic,
    *,
    stage: Stage | None = None,
    rollup: Rollup = "subtree",
    include_repeats: int = 5,
) -> DepthProfile:
    scope = QuestionScope(topic_path=str(topic.path), rollup=rollup, stage=stage)

    total = (
        await session.execute(
            select(func.count()).select_from(question_ids(scope).subquery())
        )
    ).scalar_one()

    format_mix, _ = await _mix(session, scope, QuestionProfile.format)
    depth_mix, classified = await _mix(session, scope, QuestionProfile.depth)
    archetype_mix, _ = await _mix(session, scope, QuestionProfile.option_archetype)

    statements = (
        await session.execute(
            select(func.avg(QuestionProfile.statement_count))
            .join(Question, Question.id == QuestionProfile.question_id)
            .where(Question.id.in_(question_ids(scope)))
        )
    ).scalar()

    series = await year_series(session, topic, rollup=rollup, stage=stage)
    branches = await subtree_coverage(session, topic, stage=stage)
    repeats = (
        await repeated_pairs(session, topic, rollup=rollup, stage=stage,
                             limit=include_repeats)
        if include_repeats
        else []
    )
    asked = [yc for yc in series if yc.count]

    return DepthProfile(
        topic_id=topic.id,
        path=str(topic.path),
        name_en=topic.name_en,
        name_hi=topic.name_hi,
        question_count=total,
        profiled_count=classified,
        probe_status=probe_status(total),
        first_year=asked[0].year if asked else None,
        latest_year=asked[-1].year if asked else None,
        gap_years=[yc.year for yc in series if yc.count == 0],
        format_mix=format_mix,
        depth_mix=depth_mix,
        archetype_mix=archetype_mix,
        mean_statement_count=float(statements) if statements is not None else None,
        recurrence_rate=(
            len({p.later_id for p in repeats} | {p.earlier_id for p in repeats}) / total
            if total and repeats
            else None
        ),
        year_counts=series,
        branches=branches,
        repeats=repeats,
    )


async def peer_topics(
    session: AsyncSession,
    topic: Topic,
    *,
    stage: Stage | None = None,
    limit: int = DEFAULT_PEER_LIMIT,
    min_questions: int = MIN_PEER_QUESTIONS,
) -> list[PeerTopic]:
    """Topics comparable to this one: its siblings first, then same-depth topics in the
    same subject.

    Siblings are the honest comparison — they sit at the same level of the same syllabus
    branch, so "this is what a well-drilled topic of your kind looks like" holds. Falling
    back to the whole subject widens the net when a branch has too few children, and the
    `basis` field records which comparison was actually used.
    """
    in_scope = Question.id.in_(question_ids(QuestionScope(stage=stage)))

    # Peers are compared at their own level, so a direct-tag count is the right measure
    # here — a branch and its leaf are never peers.
    base = (
        select(
            Topic.id,
            Topic.path,
            Topic.name_en,
            Topic.name_hi,
            Topic.parent_id,
            Topic.subject_id,
            Topic.depth,
            func.count(func.distinct(Question.id)).label("n"),
            func.count(func.distinct(QuestionProfile.question_id)).label("profiled"),
        )
        .select_from(Topic)
        .join(QuestionTopicMap, QuestionTopicMap.topic_id == Topic.id, isouter=True)
        .join(
            Question,
            (Question.id == QuestionTopicMap.question_id) & in_scope,
            isouter=True,
        )
        .join(
            QuestionProfile,
            (QuestionProfile.question_id == Question.id)
            & QuestionProfile.depth.is_not(None),
            isouter=True,
        )
        .where(Topic.id != topic.id, Topic.depth == topic.depth)
        .group_by(Topic.id)
        .having(func.count(func.distinct(Question.id)) >= min_questions)
        .order_by(func.count(func.distinct(Question.id)).desc())
    )

    siblings = (
        await session.execute(base.where(Topic.parent_id == topic.parent_id).limit(limit))
    ).all()
    basis = "sibling"
    if len(siblings) < 2:
        siblings = (
            await session.execute(
                base.where(Topic.subject_id == topic.subject_id).limit(limit)
            )
        ).all()
        basis = "same_depth_in_subject"

    return [
        PeerTopic(
            topic_id=r[0], path=str(r[1]), name_en=r[2], name_hi=r[3],
            subtree_count=r[7], profiled_count=r[8], basis=basis,
        )
        for r in siblings
    ]


async def transfer_prediction(
    session: AsyncSession,
    topic: Topic,
    *,
    stage: Stage | None = None,
    limit: int = DEFAULT_PEER_LIMIT,
) -> TransferPrediction:
    """What comparable topics suggest this one will be examined like.

    Deliberately deterministic: the projection is the peers' measured mix, weighted by
    how many questions each contributes. No model is asked to speculate, so the claim a
    learner sees is "topics like this one are examined this way", which the data supports,
    rather than "this will be asked", which it does not.
    """
    peers = await peer_topics(session, topic, stage=stage, limit=limit)
    profile = await build_depth_profile(
        session, topic, stage=stage, include_repeats=0
    )

    format_totals: Counter[str] = Counter()
    depth_totals: Counter[str] = Counter()
    peer_questions = 0
    peer_rates: list[float] = []

    for peer in peers:
        peer_scope = QuestionScope(topic_path=peer.path, stage=stage)
        formats, _ = await _mix(session, peer_scope, QuestionProfile.format)
        depths, _ = await _mix(session, peer_scope, QuestionProfile.depth)
        format_totals.update(formats)
        depth_totals.update(depths)
        peer_questions += peer.subtree_count
        span = (
            await session.execute(
                select(func.min(Question.year), func.max(Question.year)).where(
                    Question.id.in_(question_ids(peer_scope))
                )
            )
        ).one()
        if span[0] is not None:
            # Per peer, not pooled: summing peer counts and dividing by one mean span
            # would project the *combined* volume of every peer onto a single topic.
            peer_rates.append(peer.subtree_count / (span[1] - span[0] + 1))

    def share(counter: Counter[str]) -> dict[str, float]:
        total = sum(counter.values())
        return {k: v / total for k, v in counter.most_common()} if total else {}

    basis = peers[0].basis if peers else "none"
    # A volume projection only holds between genuine siblings. Same-depth topics from
    # elsewhere in the subject still say something useful about *how* the subject is
    # examined, but "world wars should see 20 questions a year because Indian geography
    # does" is not a claim the data supports.
    per_year = (
        sum(peer_rates) / len(peer_rates)
        if peer_rates and basis == "sibling"
        else None
    )
    untouched = [b for b in profile.branches if b.subtree_count == 0]

    notes = [
        f"projected from {len(peers)} peer topic(s) ({basis})",
        f"{peer_questions} peer questions",
    ]
    if not peers:
        notes = ["no comparable topic carries enough questions — nothing to project from"]
    elif len(peers) < 3:
        notes.append("fewer than three peers: treat as indicative only")
    if basis == "same_depth_in_subject":
        notes.append(
            "no sibling topic qualified, so peers come from the wider subject — the "
            "format mix transfers, the expected volume does not"
        )
    if peers and not format_totals and not depth_totals:
        notes.append(
            "peers are not classified yet, so only the structural half is available"
        )

    return TransferPrediction(
        topic_id=topic.id,
        peers=peers,
        peer_question_count=peer_questions,
        expected_format_mix=share(format_totals),
        expected_depth_mix=share(depth_totals),
        expected_questions_per_year=per_year,
        untouched_branches=untouched,
        confidence_note="; ".join(notes),
    )


__all__ = [
    "DEFAULT_THRESHOLD",
    "DepthProfile",
    "PeerTopic",
    "TransferPrediction",
    "build_depth_profile",
    "peer_topics",
    "transfer_prediction",
]
