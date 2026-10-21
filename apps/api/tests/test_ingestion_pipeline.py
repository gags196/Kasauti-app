"""End-to-end test of the process_scan pipeline against the local dev Postgres,
with the LLM provider faked and R2 download stubbed. Requires the taxonomy seed
(scripts/seed_taxonomy.py) to have been run."""

import kasauti_api.workers.ingestion_tasks as tasks
import pytest
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import (
    Exam,
    LlmUsageEvent,
    Paper,
    Question,
    QuestionOption,
    QuestionStimulus,
    QuestionTopicMap,
    SourceScan,
    StimulusKind,
    Topic,
)
from kasauti_api.db.models.questions import OcrStatus, QuestionLanguage, QuestionStatus
from kasauti_api.domain.llm.provider import LlmUsage
from kasauti_api.domain.llm.schemas import (
    ExtractedOption,
    ExtractedQuestion,
    ExtractedStimulus,
    ScanExtraction,
    TopicTag,
    TopicTagResult,
)
from sqlalchemy import delete, select

# Must not claim to be a real provider/model: the cost ledger's whole point is that
# every row is money actually spent, and PRICING_PER_MTOK would price a real model name.
# An unknown model prices at zero, so test runs can never inflate the cost dashboard.
FAKE_USAGE = LlmUsage(provider="fake", model="fake-standard", input_tokens=1000,
                      output_tokens=200)


class FakeProvider:
    async def parse_structured(self, *, prompt, schema, documents=None, system=None,
                               tier="standard", max_tokens=16000):
        if schema is ScanExtraction:
            return (
                ScanExtraction(
                    questions=[
                        ExtractedQuestion(
                            question_number="1(a)",
                            marks=10,
                            text_en="Find the eigenvalues of the given matrix.",
                            text_hi="दिए गए आव्यूह के आइगेनमान ज्ञात कीजिए।",
                            math_latex=r"A = \begin{pmatrix} 2 & 1 \\ 1 & 2 \end{pmatrix}",
                            confidence=0.95,
                        ),
                        ExtractedQuestion(
                            question_number="1(b)",
                            marks=10,
                            text_en="State and prove the Cayley-Hamilton theorem.",
                            confidence=0.9,
                        ),
                    ],
                    overall_confidence=0.92,
                ),
                FAKE_USAGE,
            )
        if schema is TopicTagResult:
            return (
                TopicTagResult(
                    tags=[TopicTag(
                        topic_path="maths1.linear_algebra.eigenvalues_eigenvectors",
                        confidence=0.9,
                    )]
                ),
                FAKE_USAGE,
            )
        raise AssertionError(f"unexpected schema {schema}")


@pytest.mark.asyncio
async def test_process_scan_end_to_end(monkeypatch):
    monkeypatch.setattr(tasks, "download_bytes", lambda bucket, key: b"%PDF-fake")

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
        scan = SourceScan(exam_id=exam.id, paper_id=paper.id, year=2019, r2_key="test/fake.pdf")
        session.add(scan)
        await session.commit()
        scan_id = scan.id

    try:
        result = await tasks.process_scan({"llm_provider": FakeProvider()}, scan_id)
        assert "2 questions" in result

        async with async_session_factory() as session:
            scan = (
                await session.execute(select(SourceScan).where(SourceScan.id == scan_id))
            ).scalar_one()
            assert scan.ocr_status == OcrStatus.human_review
            assert scan.ocr_confidence == pytest.approx(0.92)

            questions = list(
                (
                    await session.execute(
                        select(Question).where(Question.source_scan_id == scan_id)
                    )
                ).scalars()
            )
            assert len(questions) == 2
            assert all(q.status == QuestionStatus.human_review for q in questions)

            bilingual = next(q for q in questions if q.question_number == "1(a)")
            assert bilingual.language == QuestionLanguage.bilingual
            assert "आइगेनमान" in bilingual.question_text_hi
            assert bilingual.math_notation_latex.startswith("A =")

            tag_maps = list(
                (
                    await session.execute(
                        select(QuestionTopicMap).where(
                            QuestionTopicMap.question_id.in_([q.id for q in questions])
                        )
                    )
                ).scalars()
            )
            assert len(tag_maps) == 2  # one tag per question from the fake

            usage_rows = list(
                (
                    await session.execute(
                        select(LlmUsageEvent).where(
                            LlmUsageEvent.related_entity_type == "source_scan",
                            LlmUsageEvent.related_entity_id == str(scan_id),
                        )
                    )
                ).scalars()
            )
            # Assert the call was *recorded*, not that it cost money — the fake must
            # not claim a real model name, or every test run inflates the ledger.
            # Pricing itself is covered by test_pricing_uses_sticker_rates below.
            assert len(usage_rows) == 1
            assert usage_rows[0].input_tokens == FAKE_USAGE.input_tokens
            assert usage_rows[0].output_tokens == FAKE_USAGE.output_tokens
            assert float(usage_rows[0].cost_usd) == 0.0  # unknown model prices at zero
    finally:
        async with async_session_factory() as session:
            q_ids = [
                q.id
                for q in (
                    await session.execute(
                        select(Question).where(Question.source_scan_id == scan_id)
                    )
                ).scalars()
            ]
            if q_ids:
                await session.execute(
                    delete(QuestionTopicMap).where(QuestionTopicMap.question_id.in_(q_ids))
                )
                await session.execute(
                    delete(LlmUsageEvent).where(
                        LlmUsageEvent.related_entity_type == "question",
                        LlmUsageEvent.related_entity_id.in_([str(i) for i in q_ids]),
                    )
                )
                await session.execute(delete(Question).where(Question.id.in_(q_ids)))
            await session.execute(
                delete(LlmUsageEvent).where(
                    LlmUsageEvent.related_entity_type == "source_scan",
                    LlmUsageEvent.related_entity_id == str(scan_id),
                )
            )
            await session.execute(delete(SourceScan).where(SourceScan.id == scan_id))
            await session.commit()


class FakePrelimsProvider:
    async def parse_structured(self, *, prompt, schema, documents=None, system=None,
                               tier="standard", max_tokens=16000):
        if schema is ScanExtraction:
            return (
                ScanExtraction(
                    questions=[
                        ExtractedQuestion(
                            question_number="4",
                            marks=2,
                            text_en="Which article deals with the basic structure doctrine?",
                            text_hi="मूल संरचना सिद्धांत किस अनुच्छेद से संबंधित है?",
                            options=[
                                ExtractedOption(label="A", text_en="Article 13",
                                                text_hi="अनुच्छेद 13"),
                                ExtractedOption(label="B", text_en="Article 368",
                                                text_hi="अनुच्छेद 368"),
                                ExtractedOption(label="C", text_en="Article 356",
                                                text_hi="अनुच्छेद 356"),
                                ExtractedOption(label="D", text_en="None of the above",
                                                text_hi="उपर्युक्त में से कोई नहीं"),
                            ],
                            confidence=0.9,
                        ),
                    ],
                    overall_confidence=0.9,
                ),
                FAKE_USAGE,
            )
        if schema is TopicTagResult:
            return (
                TopicTagResult(
                    tags=[TopicTag(topic_path="gs2.constitution.basic_structure",
                                   confidence=0.85)]
                ),
                FAKE_USAGE,
            )
        raise AssertionError(f"unexpected schema {schema}")


@pytest.mark.asyncio
async def test_prelims_scan_options_and_mains_tagging(monkeypatch):
    """Prelims questions store MCQ options and tag onto the MAINS topic tree
    via paper_subject_map (prelims papers have no topics of their own)."""
    monkeypatch.setattr(tasks, "download_bytes", lambda bucket, key: b"%PDF-fake")

    async with async_session_factory() as session:
        exam = (
            await session.execute(select(Exam).where(Exam.code == "upsc-cse"))
        ).scalar_one_or_none()
        if exam is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
        paper = (
            await session.execute(
                select(Paper).where(Paper.exam_id == exam.id, Paper.code == "prelims-gs1")
            )
        ).scalar_one_or_none()
        if paper is None:
            pytest.skip("prelims paper not seeded — re-run scripts/seed_taxonomy.py")
        scan = SourceScan(exam_id=exam.id, paper_id=paper.id, year=2023,
                          r2_key="test/prelims.pdf")
        session.add(scan)
        await session.commit()
        scan_id = scan.id

    try:
        result = await tasks.process_scan({"llm_provider": FakePrelimsProvider()}, scan_id)
        assert "1 questions" in result

        async with async_session_factory() as session:
            question = (
                await session.execute(
                    select(Question).where(Question.source_scan_id == scan_id)
                )
            ).scalar_one()
            assert question.language == QuestionLanguage.bilingual

            options = (
                await session.execute(
                    select(QuestionOption)
                    .where(QuestionOption.question_id == question.id)
                    .order_by(QuestionOption.option_label)
                )
            ).scalars().all()
            assert [o.option_label for o in options] == ["A", "B", "C", "D"]
            assert all(o.is_correct is None for o in options)  # awaits answer key
            assert options[3].option_text_hi == "उपर्युक्त में से कोई नहीं"

            # The tag must point at a MAINS (gs2) topic even though the scan is prelims.
            tag = (
                await session.execute(
                    select(Topic)
                    .join(QuestionTopicMap, QuestionTopicMap.topic_id == Topic.id)
                    .where(QuestionTopicMap.question_id == question.id)
                )
            ).scalar_one()
            assert str(tag.path) == "gs2.constitution.basic_structure"
    finally:
        async with async_session_factory() as session:
            q_ids = [
                q.id
                for q in (
                    await session.execute(
                        select(Question).where(Question.source_scan_id == scan_id)
                    )
                ).scalars()
            ]
            if q_ids:
                await session.execute(
                    delete(QuestionOption).where(QuestionOption.question_id.in_(q_ids))
                )
                await session.execute(
                    delete(QuestionTopicMap).where(QuestionTopicMap.question_id.in_(q_ids))
                )
                await session.execute(
                    delete(LlmUsageEvent).where(
                        LlmUsageEvent.related_entity_type == "question",
                        LlmUsageEvent.related_entity_id.in_([str(i) for i in q_ids]),
                    )
                )
                await session.execute(delete(Question).where(Question.id.in_(q_ids)))
            await session.execute(
                delete(LlmUsageEvent).where(
                    LlmUsageEvent.related_entity_type == "source_scan",
                    LlmUsageEvent.related_entity_id == str(scan_id),
                )
            )
            await session.execute(delete(SourceScan).where(SourceScan.id == scan_id))
            await session.commit()


def test_pricing_uses_sticker_rates():
    """Pricing is checked directly, with no DB and no ledger rows written.

    Kept separate from the pipeline test so that test can use a fake model name and
    never inflate llm_usage_events — the ledger must only ever hold real spend.
    """
    from decimal import Decimal

    from kasauti_api.domain.llm.cost_ledger import compute_cost_usd

    # Sonnet 5 sticker: $3/Mtok in, $15/Mtok out.
    cost = compute_cost_usd(
        LlmUsage(provider="anthropic", model="claude-sonnet-5",
                 input_tokens=1_000_000, output_tokens=1_000_000)
    )
    assert cost == Decimal("18")

    # An unknown model must price at zero rather than guess.
    assert compute_cost_usd(
        LlmUsage(provider="fake", model="nope", input_tokens=1_000_000, output_tokens=1)
    ) == Decimal("0")


@pytest.mark.asyncio
async def test_questions_without_tables_store_sql_null_not_json_null():
    """SQLAlchemy's JSON type writes Python None as the JSON literal `null`, which is
    not SQL NULL — so `WHERE tables IS NOT NULL` would match table-less questions.
    none_as_null keeps it to two states."""
    from sqlalchemy import text

    async with async_session_factory() as session:
        exam = (
            await session.execute(select(Exam).where(Exam.code == "upsc-cse"))
        ).scalar_one_or_none()
        if exam is None:
            pytest.skip("taxonomy not seeded")
        paper = (
            await session.execute(
                select(Paper).where(Paper.exam_id == exam.id, Paper.code == "prelims-gs1")
            )
        ).scalar_one()
        q = Question(
            exam_id=exam.id, paper_id=paper.id, year=1902, question_number="1",
            language=QuestionLanguage.en, question_text_en="No tables here.",
            tables=None, status=QuestionStatus.draft,
        )
        session.add(q)
        await session.commit()
        q_id = q.id

    try:
        async with async_session_factory() as session:
            is_sql_null = (
                await session.execute(
                    text("select tables is null from questions where id = :i"),
                    {"i": q_id},
                )
            ).scalar_one()
            assert is_sql_null, "Python None must land as SQL NULL, not JSON 'null'"
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(Question).where(Question.id == q_id))
            await session.commit()


class FakeCsatProvider:
    """Two comprehension items under one passage, and a directions block whose four
    options the paper printed once but the extractor copies onto the item."""

    async def parse_structured(self, *, prompt, schema, documents=None, system=None,
                               tier="standard", max_tokens=16000):
        if schema is ScanExtraction:
            shared_options = [
                ExtractedOption(label=label, text_en=f"Option {label}",
                                text_hi=f"विकल्प {label}")
                for label in ("A", "B", "C", "D")
            ]
            return (
                ScanExtraction(
                    stimuli=[
                        ExtractedStimulus(
                            ref="passage-1",
                            kind="passage",
                            text_en="Kalagram, the cultural village, unfolded as a mosaic.",
                            text_hi="कलाग्राम, सांस्कृतिक गाँव, एक पच्चीकारी के रूप में उभरा।",
                        ),
                        ExtractedStimulus(
                            ref="directions-1",
                            kind="directions",
                            text_en="Each item contains a question followed by two statements.",
                            text_hi="प्रत्येक प्रश्नांश में एक प्रश्न है जिसके बाद दो कथन हैं।",
                        ),
                    ],
                    questions=[
                        ExtractedQuestion(
                            question_number="1",
                            text_en="What does the passage imply about the village?",
                            text_hi="परिच्छेद गाँव के बारे में क्या दर्शाता है?",
                            options=shared_options,
                            stimulus_ref="passage-1",
                            confidence=0.9,
                        ),
                        ExtractedQuestion(
                            question_number="2",
                            text_en="Which inference follows from the passage?",
                            text_hi="परिच्छेद से कौन-सा निष्कर्ष निकलता है?",
                            options=shared_options,
                            stimulus_ref="passage-1",
                            confidence=0.9,
                        ),
                        ExtractedQuestion(
                            question_number="3",
                            text_en="If x and y are integers, then is x even?",
                            text_hi="यदि x और y पूर्णांक हैं, तो क्या x सम है?",
                            options=shared_options,
                            stimulus_ref="directions-1",
                            confidence=0.9,
                        ),
                    ],
                    overall_confidence=0.9,
                ),
                FAKE_USAGE,
            )
        if schema is TopicTagResult:
            return (
                TopicTagResult(
                    tags=[TopicTag(topic_path="csat.comprehension", confidence=0.8)]
                ),
                FAKE_USAGE,
            )
        raise AssertionError(f"unexpected schema {schema}")


@pytest.mark.asyncio
async def test_process_scan_stores_one_passage_for_many_items(monkeypatch):
    """The passage is written once and pointed at, not copied into each stem — and the
    option key the paper printed once still lands as four options per item, because
    scoring and the answer-key loader both depend on that."""
    monkeypatch.setattr(tasks, "download_bytes", lambda bucket, key: b"%PDF-fake")

    async with async_session_factory() as session:
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
        scan = SourceScan(
            exam_id=exam.id, paper_id=paper.id, year=1998, r2_key="test/fake-csat.pdf"
        )
        session.add(scan)
        await session.commit()
        scan_id = scan.id

    try:
        await tasks.process_scan({"llm_provider": FakeCsatProvider()}, scan_id)

        async with async_session_factory() as session:
            stimuli = list(
                (
                    await session.execute(
                        select(QuestionStimulus).where(
                            QuestionStimulus.source_scan_id == scan_id
                        )
                    )
                ).scalars()
            )
            assert {s.ref for s in stimuli} == {"passage-1", "directions-1"}
            passage = next(s for s in stimuli if s.ref == "passage-1")
            assert passage.kind == StimulusKind.passage
            assert "कलाग्राम" in passage.text_hi

            questions = {
                q.question_number: q
                for q in (
                    await session.execute(
                        select(Question).where(Question.source_scan_id == scan_id)
                    )
                ).scalars()
            }
            assert len(questions) == 3
            # One passage, two items pointing at it — and the passage text is nowhere
            # in either stem.
            assert questions["1"].stimulus_id == questions["2"].stimulus_id == passage.id
            assert "Kalagram" not in questions["1"].question_text_en
            assert questions["3"].stimulus_id == next(
                s.id for s in stimuli if s.ref == "directions-1"
            )

            for question in questions.values():
                options = (
                    await session.execute(
                        select(QuestionOption).where(
                            QuestionOption.question_id == question.id
                        )
                    )
                ).scalars().all()
                assert len(options) == 4, question.question_number

        # Re-running extraction on the same slice must update the passage rows, not
        # duplicate them — the whole flow is built on being re-runnable.
        await tasks.process_scan({"llm_provider": FakeCsatProvider()}, scan_id)
        async with async_session_factory() as session:
            again = list(
                (
                    await session.execute(
                        select(QuestionStimulus).where(
                            QuestionStimulus.source_scan_id == scan_id
                        )
                    )
                ).scalars()
            )
            assert len(again) == 2
    finally:
        async with async_session_factory() as session:
            q_ids = [
                q.id
                for q in (
                    await session.execute(
                        select(Question).where(Question.source_scan_id == scan_id)
                    )
                ).scalars()
            ]
            if q_ids:
                await session.execute(
                    delete(QuestionTopicMap).where(QuestionTopicMap.question_id.in_(q_ids))
                )
                await session.execute(
                    delete(QuestionOption).where(QuestionOption.question_id.in_(q_ids))
                )
                await session.execute(
                    delete(LlmUsageEvent).where(
                        LlmUsageEvent.related_entity_type == "question",
                        LlmUsageEvent.related_entity_id.in_([str(i) for i in q_ids]),
                    )
                )
                await session.execute(delete(Question).where(Question.id.in_(q_ids)))
            await session.execute(
                delete(QuestionStimulus).where(QuestionStimulus.source_scan_id == scan_id)
            )
            await session.execute(
                delete(LlmUsageEvent).where(
                    LlmUsageEvent.related_entity_type == "source_scan",
                    LlmUsageEvent.related_entity_id == str(scan_id),
                )
            )
            await session.execute(delete(SourceScan).where(SourceScan.id == scan_id))
            await session.commit()
