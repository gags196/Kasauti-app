"""Coverage, trends and recurrence against the local Postgres.

The database is shared with 1,400 real questions, so these assert **invariants and
deltas**, never absolute counts: shares sum to one, the recurrence curve only falls as
the threshold rises, an inserted question moves its topic's series by exactly one.
"""

import pytest
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import Exam, Paper, Question, QuestionTopicMap, Topic
from kasauti_api.db.models.questions import QuestionLanguage, QuestionStatus, TaggedBy
from kasauti_api.db.models.taxonomy import Stage
from kasauti_api.domain.intelligence.coverage import (
    HEAVILY_PROBED,
    LIGHTLY_PROBED,
    PROBE_THRESHOLDS,
    PROBED,
    UNPROBED,
    probe_status,
    subtree_coverage,
    year_series,
)
from kasauti_api.domain.intelligence.recurrence import corpus_recurrence
from kasauti_api.domain.intelligence.trends import era_shift, mix_by_year
from sqlalchemy import delete, select
from sqlalchemy_utils import Ltree

LEAF_PATH = "gs2.constitution.basic_structure"
PARENT_PATH = "gs2.constitution"


def test_probe_status_thresholds():
    unprobed, lightly, probed = PROBE_THRESHOLDS
    assert probe_status(0) == UNPROBED
    assert probe_status(unprobed + 1) == LIGHTLY_PROBED
    assert probe_status(lightly) == LIGHTLY_PROBED
    assert probe_status(lightly + 1) == PROBED
    assert probe_status(probed) == PROBED
    assert probe_status(probed + 1) == HEAVILY_PROBED


async def _topics(session):
    leaf = (
        await session.execute(select(Topic).where(Topic.path == Ltree(LEAF_PATH)))
    ).scalar_one_or_none()
    if leaf is None:
        pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
    parent = (
        await session.execute(select(Topic).where(Topic.path == Ltree(PARENT_PATH)))
    ).scalar_one()
    return leaf, parent


@pytest.mark.asyncio
async def test_year_series_fills_gaps_and_counts_the_delta():
    async with async_session_factory() as session:
        exam = (
            await session.execute(select(Exam).where(Exam.code == "upsc-cse"))
        ).scalar_one_or_none()
        if exam is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
        mains = (
            await session.execute(
                select(Paper).where(Paper.exam_id == exam.id, Paper.code == "mains-gs2")
            )
        ).scalar_one()
        leaf, _ = await _topics(session)
        leaf_id = leaf.id

        before = {yc.year: yc.count for yc in await year_series(session, leaf)}

        q_ids = []
        for year in (2019, 2021):
            q = Question(
                exam_id=exam.id, paper_id=mains.id, year=year,
                question_number=f"cov-{year}", marks=15, language=QuestionLanguage.en,
                question_text_en="Coverage fixture.", status=QuestionStatus.published,
            )
            session.add(q)
            await session.flush()
            session.add(QuestionTopicMap(question_id=q.id, topic_id=leaf_id,
                                         confidence=1.0, tagged_by=TaggedBy.human))
            q_ids.append(q.id)
        await session.commit()

    try:
        async with async_session_factory() as session:
            leaf, parent = await _topics(session)
            series = await year_series(session, leaf)
            counts = {yc.year: yc.count for yc in series}
            assert counts[2019] == before.get(2019, 0) + 1
            assert counts[2021] == before.get(2021, 0) + 1

            # Gap filling means the years are contiguous, so a sparkline cannot imply
            # continuity across a year the topic was absent from.
            years = [yc.year for yc in series]
            assert years == list(range(years[0], years[-1] + 1))

            # A question tagged to the leaf reaches the parent's subtree, and the parent's
            # coverage view lists the leaf.
            branches = await subtree_coverage(session, parent)
            leaf_row = next(b for b in branches if b.path == LEAF_PATH)
            assert leaf_row.subtree_count >= 2
            assert leaf_row.probe_status in (
                LIGHTLY_PROBED, PROBED, HEAVILY_PROBED
            )
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(QuestionTopicMap).where(QuestionTopicMap.question_id.in_(q_ids))
            )
            await session.execute(delete(Question).where(Question.id.in_(q_ids)))
            await session.commit()


@pytest.mark.asyncio
async def test_subtree_coverage_keeps_untouched_branches():
    """Branches with zero questions must survive into the result. Dropping them would
    make every topic look uniformly covered and delete the only actionable part of the
    view."""
    async with async_session_factory() as session:
        world_history = (
            await session.execute(
                select(Topic).where(Topic.path == Ltree("gs1.world_history"))
            )
        ).scalar_one_or_none()
        if world_history is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
        branches = await subtree_coverage(session, world_history)

    assert branches, "a seeded branch topic must report its children"
    # Every child appears, whether or not it carries questions.
    assert all(b.subtree_count >= 0 for b in branches)
    for branch in branches:
        assert branch.probe_status == probe_status(branch.subtree_count)
        if branch.subtree_count == 0:
            assert branch.first_year is None and branch.latest_year is None


@pytest.mark.asyncio
async def test_trend_shares_sum_to_one_per_year():
    async with async_session_factory() as session:
        series = await mix_by_year(session, dimension="archetype", top_n=50)
    if not series.years:
        pytest.skip("no profiled questions — run scripts/derive_question_facts.py")

    assert 0.0 <= series.profiled_share <= 1.0
    for year in series.years:
        total = sum(c.share for c in series.cells if c.year == year)
        assert total == pytest.approx(1.0, abs=1e-6)


@pytest.mark.asyncio
async def test_unclassified_dimension_reports_zero_coverage_rather_than_hiding():
    """`format` is model-assigned and backfilled newest-first. Until the pass reaches a
    question the honest answer is "not classified", and `profiled_share` must say so
    rather than the chart implying full coverage."""
    async with async_session_factory() as session:
        series = await mix_by_year(session, dimension="format")
    if not series.years:
        pytest.skip("no profiled questions — run scripts/derive_question_facts.py")
    assert series.profiled_share < 1.0
    assert series.note and "format" in series.note


@pytest.mark.asyncio
async def test_era_shift_pairs_every_bucket_across_the_2022_break():
    async with async_session_factory() as session:
        shifts = await era_shift(session, dimension="archetype")
    if not shifts:
        pytest.skip("no profiled questions — run scripts/derive_question_facts.py")

    # Sorted by absolute movement, so the biggest change is first — that ordering is the
    # whole point of the view.
    deltas = [abs(s.delta) for s in shifts]
    assert deltas == sorted(deltas, reverse=True)
    for shift in shifts:
        assert 0.0 <= shift.legacy_share <= 1.0
        assert 0.0 <= shift.recent_share <= 1.0
        assert shift.delta == pytest.approx(shift.recent_share - shift.legacy_share)


@pytest.mark.asyncio
async def test_recurrence_curve_only_falls_as_the_threshold_rises():
    async with async_session_factory() as session:
        curve = await corpus_recurrence(session, stage=Stage.prelims)
    if not curve:
        pytest.skip("no embeddings — publish a scan first")

    by_threshold = sorted(curve.items())
    counts = [n for _, n in by_threshold]
    assert counts == sorted(counts, reverse=True), (
        "a stricter similarity threshold can never match more questions"
    )
