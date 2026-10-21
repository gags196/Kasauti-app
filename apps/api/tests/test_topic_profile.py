"""Topic depth profile and the peer/transfer projection.

Shares the database with 1,400 real questions, so assertions are invariants and deltas.
The invariants matter more than the numbers here: this is the feature most able to state
something the data does not support, so the tests are mostly about what it *refuses* to
claim.
"""

import pytest
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import Exam, Paper, Question, QuestionTopicMap, Topic
from kasauti_api.db.models.questions import QuestionLanguage, QuestionStatus, TaggedBy
from kasauti_api.domain.intelligence.topic_profile import (
    build_depth_profile,
    peer_topics,
    transfer_prediction,
)
from sqlalchemy import delete, select
from sqlalchemy_utils import Ltree

LEAF_PATH = "gs2.constitution.basic_structure"
THIN_LEAF_PATH = "gs1.world_history.world_wars"


async def _topic(session, path: str) -> Topic:
    topic = (
        await session.execute(select(Topic).where(Topic.path == Ltree(path)))
    ).scalar_one_or_none()
    if topic is None:
        pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
    return topic


@pytest.mark.asyncio
async def test_depth_profile_counts_the_delta_and_reports_classified_share():
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
        topic = await _topic(session, LEAF_PATH)
        topic_id = topic.id
        before = (await build_depth_profile(session, topic, include_repeats=0)).question_count

        q_ids = []
        for year in (2018, 2020):
            q = Question(
                exam_id=exam.id, paper_id=mains.id, year=year,
                question_number=f"prof-{year}", marks=15, language=QuestionLanguage.en,
                question_text_en="Profile fixture.", status=QuestionStatus.published,
            )
            session.add(q)
            await session.flush()
            session.add(QuestionTopicMap(question_id=q.id, topic_id=topic_id,
                                         confidence=1.0, tagged_by=TaggedBy.human))
            q_ids.append(q.id)
        await session.commit()

    try:
        async with async_session_factory() as session:
            topic = await _topic(session, LEAF_PATH)
            profile = await build_depth_profile(session, topic, include_repeats=0)
            assert profile.question_count == before + 2
            assert profile.path == LEAF_PATH
            # Classified share is a real ratio, never assumed to be complete: the
            # fixtures above carry no profile row at all.
            assert 0.0 <= profile.classified_share <= 1.0
            assert profile.profiled_count <= profile.question_count
            assert profile.probe_status
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(QuestionTopicMap).where(QuestionTopicMap.question_id.in_(q_ids))
            )
            await session.execute(delete(Question).where(Question.id.in_(q_ids)))
            await session.commit()


@pytest.mark.asyncio
async def test_peers_are_never_the_topic_itself_and_sit_at_its_level():
    async with async_session_factory() as session:
        topic = await _topic(session, LEAF_PATH)
        peers = await peer_topics(session, topic)
        depth = topic.depth
        topic_id = topic.id

    if not peers:
        pytest.skip("no peers available in this corpus")
    assert all(p.topic_id != topic_id for p in peers)
    async with async_session_factory() as session:
        for peer in peers:
            row = (
                await session.execute(
                    select(Topic.depth).where(Topic.path == Ltree(peer.path))
                )
            ).scalar_one()
            # A branch and one of its own leaves are not peers.
            assert row == depth


@pytest.mark.asyncio
async def test_volume_is_not_projected_from_unrelated_topics():
    """When no sibling qualifies, peers are drawn from the wider subject. The format mix
    still transfers — that is how the subject is examined — but "world wars should see
    twenty questions a year because Indian geography does" is not supported, so the
    volume projection must be withheld and the reason stated."""
    async with async_session_factory() as session:
        topic = await _topic(session, THIN_LEAF_PATH)
        prediction = await transfer_prediction(session, topic)

    if not prediction.peers:
        pytest.skip("no peers available in this corpus")
    if prediction.peers[0].basis == "same_depth_in_subject":
        assert prediction.expected_questions_per_year is None
        assert "expected volume does not" in prediction.confidence_note
    else:
        assert prediction.expected_questions_per_year is not None


@pytest.mark.asyncio
async def test_transfer_prediction_always_carries_a_confidence_note():
    """A projection built from two peers is not the same object as one built from
    thirty, and the difference has to travel with the number."""
    async with async_session_factory() as session:
        for path in (LEAF_PATH, THIN_LEAF_PATH):
            topic = await _topic(session, path)
            prediction = await transfer_prediction(session, topic)
            assert prediction.confidence_note
            assert prediction.topic_id == topic.id
            if len(prediction.peers) < 3 and prediction.peers:
                assert "indicative only" in prediction.confidence_note
            for mix in (prediction.expected_format_mix, prediction.expected_depth_mix):
                if mix:
                    assert sum(mix.values()) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.asyncio
async def test_unprobed_topic_profiles_cleanly_rather_than_erroring():
    async with async_session_factory() as session:
        topic = await _topic(session, THIN_LEAF_PATH)
        profile = await build_depth_profile(session, topic)

    if profile.question_count:
        pytest.skip(f"{THIN_LEAF_PATH} now carries questions")
    assert profile.probe_status == "unprobed"
    assert profile.first_year is None and profile.latest_year is None
    assert profile.recurrence_rate is None
    assert profile.format_mix == {} and profile.repeats == []
