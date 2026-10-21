"""Candidate-topic selection, including the per-subject depth cap.

The cap exists so a paper that only brushes a subject does not drag that subject's
whole subtree into every tagging prompt — which both invites spuriously precise tags
and inflates a prompt that is resent on every call.
"""

import pytest
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import Paper, PaperSubjectMap, Topic
from kasauti_api.domain.ingestion.tag import candidate_topics_for_paper
from sqlalchemy import select


@pytest.mark.asyncio
async def test_prelims_gets_capped_gs4_but_full_depth_elsewhere():
    async with async_session_factory() as session:
        paper = (
            await session.execute(select(Paper).where(Paper.code == "prelims-gs1"))
        ).scalar_one_or_none()
        if paper is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")

        topics = await candidate_topics_for_paper(session, paper.id)
        by_subject: dict[str, list[Topic]] = {}
        for t in topics:
            by_subject.setdefault(str(t.path).split(".")[0], []).append(t)

        # Ethics is a rare Prelims visitor, so only the broad headings are offered.
        gs4 = by_subject.get("gs4", [])
        assert gs4, "gs4 must still be reachable — 2026 tested ethics three times"
        assert all(t.depth <= 1 for t in gs4), "gs4 must be capped at broad headings"

        # Subjects Prelims tests heavily keep their full depth.
        assert any(t.depth >= 2 for t in by_subject.get("gs1", [])), "gs1 must be full depth"
        assert any(t.depth >= 2 for t in by_subject.get("gs3", [])), "gs3 must be full depth"


@pytest.mark.asyncio
async def test_cap_does_not_affect_the_subject_s_own_paper():
    """The cap belongs to the mapping, not the subject: Mains GS4 still needs every
    fine-grained ethics topic for its one-pagers."""
    async with async_session_factory() as session:
        paper = (
            await session.execute(select(Paper).where(Paper.code == "mains-gs4"))
        ).scalar_one_or_none()
        if paper is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")

        topics = await candidate_topics_for_paper(session, paper.id)
        assert any(t.depth >= 2 for t in topics), "mains-gs4 must keep full depth"


@pytest.mark.asyncio
async def test_cap_is_recorded_on_the_mapping_row():
    async with async_session_factory() as session:
        paper = (
            await session.execute(select(Paper).where(Paper.code == "prelims-gs1"))
        ).scalar_one_or_none()
        if paper is None:
            pytest.skip("taxonomy not seeded")
        caps = (
            await session.execute(
                select(PaperSubjectMap.max_topic_depth).where(
                    PaperSubjectMap.paper_id == paper.id
                )
            )
        ).scalars().all()
        # Exactly one mapped subject (gs4) is capped; the rest are uncapped.
        assert sorted(c is None for c in caps) == [False, True, True, True]
