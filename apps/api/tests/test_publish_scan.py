"""Readiness checks and publishing, against the local dev Postgres.

Publishing is the point where a question becomes learner-visible, and the CLI path
(scripts/publish_scan.py) has no human looking at the rows the way the admin action
does. These tests pin the checks that stand in for that pair of eyes.

Shares the database with real data, so every row created here is torn down and no
assertion touches a global aggregate.
"""

import pytest
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import (
    Exam,
    Paper,
    Question,
    QuestionOption,
    QuestionStimulus,
    QuestionTopicMap,
    SourceScan,
    StimulusKind,
    Topic,
)
from kasauti_api.db.models.questions import (
    OcrStatus,
    QuestionLanguage,
    QuestionStatus,
    TaggedBy,
)
from kasauti_api.domain.ingestion.publish import check_scan_ready, publish_scan
from sqlalchemy import delete, select


async def _fixture_scan(session, *, bilingual=True, tagged=True, options=4, marks=None):
    """A prelims-shaped scan with one question, dialled to whatever defect is under test."""
    exam = (
        await session.execute(select(Exam).where(Exam.code == "upsc-cse"))
    ).scalar_one_or_none()
    if exam is None:
        pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
    paper = (
        await session.execute(
            select(Paper).where(Paper.exam_id == exam.id, Paper.code == "prelims-gs1")
        )
    ).scalar_one()
    topic = (await session.execute(select(Topic).limit(1))).scalar_one()

    scan = SourceScan(
        exam_id=exam.id, paper_id=paper.id, year=1999, r2_key="test/publish-fixture.pdf"
    )
    session.add(scan)
    await session.flush()

    question = Question(
        exam_id=exam.id,
        paper_id=paper.id,
        year=1999,
        question_number="1",
        marks=marks,
        language=QuestionLanguage.bilingual,
        question_text_en="Which of the following is correct?",
        question_text_hi="निम्नलिखित में से कौन-सा सही है?" if bilingual else None,
        source_scan_id=scan.id,
        status=QuestionStatus.human_review,
    )
    session.add(question)
    await session.flush()

    for label in ["A", "B", "C", "D"][:options]:
        session.add(
            QuestionOption(question_id=question.id, option_label=label, option_text_en=label)
        )
    if tagged:
        session.add(
            QuestionTopicMap(
                question_id=question.id,
                topic_id=topic.id,
                confidence=0.9,
                tagged_by=TaggedBy.model,
            )
        )
    await session.commit()
    return scan.id, question.id


async def _cleanup(scan_id: int, question_id: int) -> None:
    async with async_session_factory() as session:
        await session.execute(
            delete(QuestionTopicMap).where(QuestionTopicMap.question_id == question_id)
        )
        await session.execute(
            delete(QuestionOption).where(QuestionOption.question_id == question_id)
        )
        await session.execute(delete(Question).where(Question.id == question_id))
        await session.execute(delete(SourceScan).where(SourceScan.id == scan_id))
        await session.commit()


@pytest.mark.asyncio
async def test_ready_scan_publishes_and_backfills_only_null_marks():
    async with async_session_factory() as session:
        scan_id, question_id = await _fixture_scan(session)
    try:
        async with async_session_factory() as session:
            report = await check_scan_ready(session, scan_id)
            assert report.ok, report.problems()

            result = await publish_scan(session, scan_id, marks=2.0)
            await session.commit()
            assert result.published_ids == [question_id]
            assert result.marks_backfilled == 1

        async with async_session_factory() as session:
            question = (
                await session.execute(select(Question).where(Question.id == question_id))
            ).scalar_one()
            assert question.status == QuestionStatus.published
            assert float(question.marks) == 2.0
            scan = (
                await session.execute(select(SourceScan).where(SourceScan.id == scan_id))
            ).scalar_one()
            assert scan.ocr_status == OcrStatus.published

            # Re-publishing with a different figure must not overwrite a set value:
            # marks already on the row were printed or hand-corrected.
            again = await publish_scan(session, scan_id, marks=2.5)
            await session.commit()
            assert again.marks_backfilled == 0
            question = (
                await session.execute(select(Question).where(Question.id == question_id))
            ).scalar_one()
            assert float(question.marks) == 2.0
    finally:
        await _cleanup(scan_id, question_id)


@pytest.mark.asyncio
async def test_untagged_question_is_not_ready():
    async with async_session_factory() as session:
        scan_id, question_id = await _fixture_scan(session, tagged=False)
    try:
        async with async_session_factory() as session:
            report = await check_scan_ready(session, scan_id)
            assert not report.ok
            assert report.untagged == ["1"]
    finally:
        await _cleanup(scan_id, question_id)


@pytest.mark.asyncio
async def test_missing_hindi_is_not_ready():
    """The learner UI shows both languages together, so one-language rows are holes."""
    async with async_session_factory() as session:
        scan_id, question_id = await _fixture_scan(session, bilingual=False)
    try:
        async with async_session_factory() as session:
            report = await check_scan_ready(session, scan_id)
            assert not report.ok
            assert report.missing_hi == ["1"]
            assert report.missing_en == []
    finally:
        await _cleanup(scan_id, question_id)


@pytest.mark.asyncio
async def test_dropped_mcq_option_is_not_ready():
    """Three options means extraction lost one — and the answer key would then be
    applied against an incomplete set."""
    async with async_session_factory() as session:
        scan_id, question_id = await _fixture_scan(session, options=3)
    try:
        async with async_session_factory() as session:
            report = await check_scan_ready(session, scan_id)
            assert not report.ok
            assert report.bad_option_count == [("1", 3)]
    finally:
        await _cleanup(scan_id, question_id)


async def _fixture_stimulus_scan(session, *, bilingual_passage=True, attach=True):
    """Two comprehension items under one passage — the CSAT shape.

    `attach` off simulates the failure the extractor can produce quietly: an item that
    named a passage in its `stimulus_ref` but never got linked to one.
    """
    exam = (
        await session.execute(select(Exam).where(Exam.code == "upsc-cse"))
    ).scalar_one_or_none()
    if exam is None:
        pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
    paper = (
        await session.execute(
            select(Paper).where(Paper.exam_id == exam.id, Paper.code == "prelims-gs2")
        )
    ).scalar_one()
    topic = (await session.execute(select(Topic).limit(1))).scalar_one()

    scan = SourceScan(
        exam_id=exam.id,
        paper_id=paper.id,
        year=1999,
        r2_key="test/stimulus-fixture.pdf",
        raw_extraction_json={
            "questions": [
                {"question_number": "1", "stimulus_ref": "passage-1"},
                {"question_number": "2", "stimulus_ref": "passage-1"},
            ]
        },
    )
    session.add(scan)
    await session.flush()

    stimulus = QuestionStimulus(
        paper_id=paper.id,
        year=1999,
        source_scan_id=scan.id,
        kind=StimulusKind.passage,
        ref="passage-1",
        text_en="A passage about a cultural village.",
        text_hi="एक सांस्कृतिक गाँव पर आधारित परिच्छेद।" if bilingual_passage else None,
    )
    session.add(stimulus)
    await session.flush()

    question_ids = []
    for number in ("1", "2"):
        question = Question(
            exam_id=exam.id,
            paper_id=paper.id,
            year=1999,
            question_number=number,
            language=QuestionLanguage.bilingual,
            question_text_en="What does the passage imply?",
            question_text_hi="परिच्छेद से क्या निहित होता है?",
            source_scan_id=scan.id,
            stimulus_id=stimulus.id if attach else None,
            status=QuestionStatus.human_review,
        )
        session.add(question)
        await session.flush()
        for label in ["A", "B", "C", "D"]:
            session.add(
                QuestionOption(
                    question_id=question.id, option_label=label, option_text_en=label
                )
            )
        session.add(
            QuestionTopicMap(
                question_id=question.id,
                topic_id=topic.id,
                confidence=0.9,
                tagged_by=TaggedBy.model,
            )
        )
        question_ids.append(question.id)
    await session.commit()
    return scan.id, question_ids, stimulus.id


async def _cleanup_stimulus(scan_id: int, question_ids: list[int], stimulus_id: int) -> None:
    async with async_session_factory() as session:
        await session.execute(
            delete(QuestionTopicMap).where(QuestionTopicMap.question_id.in_(question_ids))
        )
        await session.execute(
            delete(QuestionOption).where(QuestionOption.question_id.in_(question_ids))
        )
        await session.execute(delete(Question).where(Question.id.in_(question_ids)))
        await session.execute(
            delete(QuestionStimulus).where(QuestionStimulus.id == stimulus_id)
        )
        await session.execute(delete(SourceScan).where(SourceScan.id == scan_id))
        await session.commit()


@pytest.mark.asyncio
async def test_two_items_sharing_one_passage_are_ready():
    """The passage is stored once and both items point at it — the whole reason the
    table exists, so it must pass the gate rather than look like a defect."""
    async with async_session_factory() as session:
        scan_id, question_ids, stimulus_id = await _fixture_stimulus_scan(session)
    try:
        async with async_session_factory() as session:
            report = await check_scan_ready(session, scan_id)
            assert report.ok, report.problems()
            assert report.total == 2
    finally:
        await _cleanup_stimulus(scan_id, question_ids, stimulus_id)


@pytest.mark.asyncio
async def test_passage_missing_hindi_is_not_ready():
    """A one-language passage is a hole for half the learners, exactly as a
    one-language question is."""
    async with async_session_factory() as session:
        scan_id, question_ids, stimulus_id = await _fixture_stimulus_scan(
            session, bilingual_passage=False
        )
    try:
        async with async_session_factory() as session:
            report = await check_scan_ready(session, scan_id)
            assert not report.ok
            assert report.stimulus_missing_hi == ["passage-1"]
            assert report.stimulus_missing_en == []
    finally:
        await _cleanup_stimulus(scan_id, question_ids, stimulus_id)


@pytest.mark.asyncio
async def test_item_whose_passage_never_linked_is_not_ready():
    """The dangerous case: the row looks like a self-contained question, so nothing
    else would ever notice that its passage is missing. Caught by comparing the
    committed rows against what extraction said."""
    async with async_session_factory() as session:
        scan_id, question_ids, stimulus_id = await _fixture_stimulus_scan(
            session, attach=False
        )
    try:
        async with async_session_factory() as session:
            report = await check_scan_ready(session, scan_id)
            assert not report.ok
            assert sorted(report.unresolved_stimulus_ref) == [
                ("1", "passage-1"),
                ("2", "passage-1"),
            ]
            assert report.orphan_stimuli == ["passage-1"]
    finally:
        await _cleanup_stimulus(scan_id, question_ids, stimulus_id)
